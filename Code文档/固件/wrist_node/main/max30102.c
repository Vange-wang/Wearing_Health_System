#include "max30102.h"
#include <stdbool.h>
#include <string.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "rom/ets_sys.h"
#include "esp_rom_sys.h"
#include "soc/gpio_struct.h"
#include "soc/io_mux_reg.h"
#include "hal/gpio_ll.h"

static const char *TAG = "max30102";

/* 寄存器 */
#define REG_INTR_STATUS_1 0x00
#define REG_INTR_STATUS_2 0x01
#define REG_INTR_ENABLE_1 0x02
#define REG_INTR_ENABLE_2 0x03
#define REG_FIFO_WR_PTR   0x04
#define REG_OVF_COUNTER   0x05
#define REG_FIFO_RD_PTR   0x06
#define REG_FIFO_DATA     0x07
#define REG_FIFO_CONFIG   0x08
#define REG_MODE_CONFIG   0x09
#define REG_SPO2_CONFIG   0x0A
#define REG_LED1_PA       0x0C
#define REG_LED2_PA       0x0D
#define REG_MLED_CTRL1    0x11
#define REG_PART_ID       0xFF

#define PIN_SDA           GPIO_NUM_4
#define PIN_SCL           GPIO_NUM_5

#define EXPECTED_PART_ID  0x15

/* LED 电流（0.2mA/步）：0x17=4.6mA（2026-08-23 微动修复最终值）。
 * 实测对比：3mA irAC~250（信噪比不足）；6mA irAC~1300 但重搏切迹过强，
 * 0.45s 峰间距仍漏 0.5-0.6s 次峰 → HR 高估（104-120 vs 真实 78）。
 * 4.6mA irAC~500：SNR 足够且切迹弱，锁定值与血氧仪吻合（63-82）。 */
#define LED_CURRENT       0x17
#define FIFO_CONFIG_VALUE 0x0F
#define SPO2_CONFIG_VALUE 0x26
#define MLED_CTRL1_VALUE  0x21
#define SPO2_MODE_VALUE   0x03
#define RESET_VALUE       0x40

/* 连续失败超过该次数（≈1 秒）判定总线卡死，触发恢复 */
#define I2C_FAIL_RECOVER  100

static uint8_t s_part_id = 0;
static int s_consec_fails = 0;
static max30102_stats_t s_stats;
static bool s_window_invalidated;

static esp_err_t read_regs(uint8_t reg, uint8_t *buf, size_t len);
typedef esp_err_t (*register_writer_fn)(uint8_t reg, uint8_t value);
typedef esp_err_t (*register_reader_fn)(uint8_t reg, uint8_t *buf, size_t len);

static esp_err_t record_transaction(bool ok)
{
    if (ok) {
        s_consec_fails = 0;
    } else {
        ++s_consec_fails;
        ++s_stats.transaction_errors;
    }
    s_stats.consecutive_failures = (uint32_t)s_consec_fails;
    return ok ? ESP_OK : ESP_FAIL;
}

/* ================= 软件 I2C（bit-bang ~100kHz） =================
 * 原因：MAX30102 在采样窗口会 NACK，且被中断的多字节读会卡死 SCL。
 * IDF 硬件 I2C 驱动（新 i2c_master 无超时忙等 / legacy 恢复困难）都会因此
 * 出问题。软件 I2C 对总线完全可控：NACK 即时检测、卡死随时打脉冲解锁。 */

static inline void scl_low(void)  { gpio_set_level(PIN_SCL, 0); }
static inline void scl_high(void) { gpio_set_level(PIN_SCL, 1); }
static inline void sda_low(void)  { gpio_set_level(PIN_SDA, 0); }
static inline void sda_high(void) { gpio_set_level(PIN_SDA, 1); }
static inline int  sda_read(void) { return gpio_get_level(PIN_SDA); }

/* SDA 方向切换（底层寄存器，避免 gpio_config 刷日志）：
 * OUTPUT_OD 模式下输入功能可能未启用导致 sda_read 恒 0，读数据前必须切纯输入 */
static inline void sda_set_in(void)  { GPIO.enable_w1tc.val = (1U << PIN_SDA); }
static inline void sda_set_out(void) { GPIO.enable_w1ts.val = (1U << PIN_SDA); }

static void i2c_delay(void) { esp_rom_delay_us(5); }   /* ~90kHz，留足余量 */

static void i2c_start(void)
{
    sda_high();
    i2c_delay();
    scl_high();
    i2c_delay();
    sda_low();
    i2c_delay();
    scl_low();
    i2c_delay();
}

static void i2c_stop(void)
{
    sda_low();
    i2c_delay();
    scl_high();
    i2c_delay();
    sda_high();
    i2c_delay();
}

/* 返回 false = NACK */
static bool i2c_write_byte(uint8_t b)
{
    for (int i = 7; i >= 0; i--) {
        if (b & (1 << i)) {
            sda_high();
        } else {
            sda_low();
        }
        i2c_delay();
        scl_high();
        i2c_delay();
        scl_low();
        i2c_delay();
    }
    sda_high();                 /* 释放 SDA 等 ACK */
    i2c_delay();
    scl_high();
    i2c_delay();
    bool ack = (sda_read() == 0);
    scl_low();
    i2c_delay();
    sda_high();
    return ack;
}

static uint8_t i2c_read_byte(bool ack)
{
    uint8_t b = 0;
    sda_set_in();               /* SDA 切纯输入（开漏输出下输入可能被禁用，读恒 0） */
    for (int i = 7; i >= 0; i--) {
        scl_high();
        i2c_delay();
        if (sda_read()) {
            b |= (1 << i);
        }
        scl_low();
        i2c_delay();
    }
    sda_set_out();              /* 回开漏输出，发 ACK/NACK */
    if (ack) {
        sda_low();
    } else {
        sda_high();
    }
    i2c_delay();
    scl_high();
    i2c_delay();
    scl_low();
    i2c_delay();
    sda_high();
    return b;
}

/* 写寄存器：全部字节 ACK 才成功 */
static esp_err_t write_reg(uint8_t reg, uint8_t val)
{
    i2c_start();
    bool ok = i2c_write_byte(MAX30102_I2C_ADDR << 1);
    if (ok) ok = i2c_write_byte(reg);
    if (ok) ok = i2c_write_byte(val);
    i2c_stop();
    return record_transaction(ok);
}

static esp_err_t read_reg(uint8_t reg, uint8_t *val)
{
    return read_regs(reg, val, 1);
}

/* 读寄存器：repeated start 时序 */
static esp_err_t read_regs(uint8_t reg, uint8_t *buf, size_t len)
{
    i2c_start();
    bool ok = i2c_write_byte(MAX30102_I2C_ADDR << 1);
    if (ok) ok = i2c_write_byte(reg);
    if (ok) {
        i2c_start();            /* repeated start */
        ok = i2c_write_byte((MAX30102_I2C_ADDR << 1) | 1);
    }
    if (ok) {
        for (size_t i = 0; i < len; i++) {
            buf[i] = i2c_read_byte(i < len - 1);
        }
    }
    i2c_stop();
    return record_transaction(ok);
}

static esp_err_t configure_sensor(register_writer_fn writer)
{
    if (writer == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t err;
    if ((err = writer(REG_FIFO_CONFIG, FIFO_CONFIG_VALUE)) != ESP_OK) return err;
    if ((err = writer(REG_SPO2_CONFIG, SPO2_CONFIG_VALUE)) != ESP_OK) return err;
    if ((err = writer(REG_LED1_PA, LED_CURRENT)) != ESP_OK) return err;
    if ((err = writer(REG_LED2_PA, LED_CURRENT)) != ESP_OK) return err;
    if ((err = writer(REG_MLED_CTRL1, MLED_CTRL1_VALUE)) != ESP_OK) return err;
    if ((err = writer(REG_INTR_ENABLE_1, 0x00)) != ESP_OK) return err;
    if ((err = writer(REG_INTR_ENABLE_2, 0x00)) != ESP_OK) return err;
    return writer(REG_MODE_CONFIG, SPO2_MODE_VALUE);
}

static esp_err_t clear_fifo(register_writer_fn writer)
{
    esp_err_t err;
    if ((err = writer(REG_FIFO_WR_PTR, 0x00)) != ESP_OK) return err;
    if ((err = writer(REG_OVF_COUNTER, 0x00)) != ESP_OK) return err;
    return writer(REG_FIFO_RD_PTR, 0x00);
}

static esp_err_t recover_with_writer(register_writer_fn writer, bool pulse_bus)
{
    ++s_stats.recovery_attempts;
    if (pulse_bus) {
        ESP_LOGW(TAG, "I2C 连续失败 %d 次，尝试总线恢复", s_consec_fails);
        for (int i = 0; i < 10; ++i) {
            scl_low();
            ets_delay_us(5);
            scl_high();
            ets_delay_us(5);
        }
        i2c_stop();
    }

    esp_err_t err = writer(REG_MODE_CONFIG, RESET_VALUE);
    if (err == ESP_OK && pulse_bus) {
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    if (err == ESP_OK) {
        err = configure_sensor(writer);
    }
    if (err == ESP_OK) {
        err = clear_fifo(writer);
    }
    if (err != ESP_OK) {
        ++s_stats.recovery_failures;
        ESP_LOGE(TAG, "总线恢复失败");
        return err;
    }
    s_consec_fails = 0;
    s_stats.consecutive_failures = 0;
    ESP_LOGW(TAG, "总线恢复完成");
    return ESP_OK;
}

esp_err_t max30102_recover(void)
{
    return recover_with_writer(write_reg, true);
}

static esp_err_t handle_fifo_overflow(uint8_t overflow,
                                      register_reader_fn reader,
                                      register_writer_fn writer)
{
    if (overflow == 0) {
        return ESP_OK;
    }
    ++s_stats.fifo_overflows;
    s_window_invalidated = true;
    /* A complete FIFO pop advances RD_PTR and resets the saturated overflow
     * counter.  Do this before pointer clearing so overflow recovery cannot
     * deadlock on modules that ignore direct OVF_COUNTER writes while full. */
    uint8_t discarded_sample[6];
    esp_err_t err = reader(REG_FIFO_DATA, discarded_sample,
                           sizeof(discarded_sample));
    if (err != ESP_OK) {
        return err;
    }
    return clear_fifo(writer);
}

esp_err_t max30102_init(void)
{
    /* GPIO 开漏 + 上拉（与硬件 I2C 等效，模块板载上拉 + 内部上拉兜底）
     * 注意：必须用 gpio_config 一次配齐方向+上拉——分开调 set_direction/set_pull_mode
     * 会互相覆盖（后者把方向重置为禁用）。 */
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << PIN_SDA) | (1ULL << PIN_SCL),
        .mode = GPIO_MODE_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&io);
    if (err != ESP_OK) {
        return err;
    }
    /* 关键 1：gpio_config 后输出锁存默认 0，开漏输出会把 SDA/SCL 主动拉低——
     * 必须立即置高释放总线（空闲电平恢复上拉） */
    sda_high();
    scl_high();
    /* 关键 2：IDF 5.2 的 gpio_config 对输出模式会关闭 IO_MUX 输入使能（FUN_IE），
     * 导致 gpio_get_level 恒读 0（ACK 假阳性）。必须显式重开输入。 */
    gpio_ll_input_enable(&GPIO, PIN_SDA);
    gpio_ll_input_enable(&GPIO, PIN_SCL);

    /* 上电复位 */
    err = write_reg(REG_MODE_CONFIG, RESET_VALUE);
    if (err != ESP_OK) {
        return err;
    }
    vTaskDelay(pdMS_TO_TICKS(20));

    /* 芯片 ID 校验 */
    if (read_reg(REG_PART_ID, &s_part_id) != ESP_OK || s_part_id != EXPECTED_PART_ID) {
        ESP_LOGE(TAG, "PartID=0x%02x，期望 0x%02x", s_part_id, EXPECTED_PART_ID);
        return ESP_ERR_INVALID_RESPONSE;
    }

    err = configure_sensor(write_reg);
    if (err != ESP_OK) {
        return err;
    }
    err = clear_fifo(write_reg);
    if (err != ESP_OK) {
        return err;
    }

    s_consec_fails = 0;
    ESP_LOGI(TAG, "初始化完成 PartID=0x%02x（软件I2C/100Hz/215µs/%.1fmA）",
             s_part_id, (float)LED_CURRENT * 0.2f);
    return ESP_OK;
}

uint8_t max30102_get_part_id(void)
{
    return s_part_id;
}

int max30102_read_fifo(max30102_sample_t *out, int max_samples)
{
    if (out == NULL || max_samples <= 0) {
        return 0;
    }
    /* 连续失败判定总线卡死 → 恢复 */
    if (s_consec_fails >= I2C_FAIL_RECOVER) {
        (void)max30102_recover();
        return 0;
    }

    uint8_t overflow = 0;
    if (read_reg(REG_OVF_COUNTER, &overflow) != ESP_OK) {
        return 0;
    }
    if (overflow != 0) {
        ESP_LOGW(TAG, "FIFO overflow count=%u; discarding contaminated window",
                 overflow & 0x1F);
        if (handle_fifo_overflow(overflow, read_regs, write_reg) != ESP_OK) {
            ESP_LOGE(TAG, "FIFO overflow clear failed");
        }
        return 0;
    }

    uint8_t rd = 0, wr = 0;
    if (read_reg(REG_FIFO_RD_PTR, &rd) != ESP_OK ||
        read_reg(REG_FIFO_WR_PTR, &wr) != ESP_OK) {
        return 0;
    }
    int avail = (wr - rd) & 0x1F;
    if (avail == 0) {
        return 0;
    }
    if (avail > max_samples) {
        avail = max_samples;
    }

    static uint8_t buf[32 * 6];
    if (read_regs(REG_FIFO_DATA, buf, (size_t)avail * 6) != ESP_OK) {
        return 0;
    }

    /* 每样本 6 字节：前 3 字节 RED(LED1)，后 3 字节 IR(LED2)，18-bit */
    for (int i = 0; i < avail; i++) {
        const uint8_t *p = buf + i * 6;
        out[i].red = ((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2];
        out[i].ir  = ((uint32_t)p[3] << 16) | ((uint32_t)p[4] << 8) | p[5];
        out[i].red &= 0x3FFFF;
        out[i].ir  &= 0x3FFFF;
    }
    /* 读指针随读 FIFO_DATA 自动推进，无需（也不能）写 RD_PTR */
    return avail;
}

void max30102_get_stats(max30102_stats_t *out)
{
    if (out != NULL) {
        *out = s_stats;
        out->consecutive_failures = (uint32_t)s_consec_fails;
    }
}

bool max30102_take_window_invalidated(void)
{
    bool invalidated = s_window_invalidated;
    s_window_invalidated = false;
    return invalidated;
}

#ifdef MAX30102_SELF_TEST
static int s_test_write_call;
static int s_test_fail_call;
static int s_test_read_call;
static uint8_t s_test_read_reg;
static size_t s_test_read_len;

static esp_err_t selftest_writer(uint8_t reg, uint8_t value)
{
    (void)reg;
    (void)value;
    ++s_test_write_call;
    return s_test_write_call == s_test_fail_call ? ESP_FAIL : ESP_OK;
}

static esp_err_t selftest_reader(uint8_t reg, uint8_t *buf, size_t len)
{
    s_test_read_call++;
    s_test_read_reg = reg;
    s_test_read_len = len;
    memset(buf, 0, len);
    return ESP_OK;
}

esp_err_t max30102_fault_injection_selftest(void)
{
    memset(&s_stats, 0, sizeof(s_stats));
    s_consec_fails = 0;
    s_window_invalidated = false;

    s_test_write_call = 0;
    s_test_fail_call = 2;
    if (configure_sensor(selftest_writer) == ESP_OK) {
        return ESP_FAIL;
    }

    s_test_write_call = 0;
    s_test_fail_call = 1;
    if (recover_with_writer(selftest_writer, false) == ESP_OK ||
        s_stats.recovery_failures != 1) {
        return ESP_FAIL;
    }

    s_test_write_call = 0;
    s_test_fail_call = -1;
    s_test_read_call = 0;
    s_test_read_reg = 0;
    s_test_read_len = 0;
    if (handle_fifo_overflow(1, selftest_reader, selftest_writer) != ESP_OK ||
        s_test_read_call != 1 ||
        s_test_read_reg != REG_FIFO_DATA ||
        s_test_read_len != 6 ||
        s_stats.fifo_overflows != 1 ||
        !max30102_take_window_invalidated() ||
        max30102_take_window_invalidated()) {
        return ESP_FAIL;
    }

    s_consec_fails = 2;
    (void)record_transaction(true);
    if (s_consec_fails != 0 || s_stats.consecutive_failures != 0) {
        return ESP_FAIL;
    }
    memset(&s_stats, 0, sizeof(s_stats));
    s_consec_fails = 0;
    s_window_invalidated = false;
    return ESP_OK;
}
#endif
