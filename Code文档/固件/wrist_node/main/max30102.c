#include "max30102.h"
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

/* 连续失败超过该次数（≈1 秒）判定总线卡死，触发恢复 */
#define I2C_FAIL_RECOVER  100

static uint8_t s_part_id = 0;
static int s_consec_fails = 0;

static esp_err_t read_regs(uint8_t reg, uint8_t *buf, size_t len);

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
    if (!ok) {
        s_consec_fails++;
    }
    return ok ? ESP_OK : ESP_FAIL;
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
    if (ok) {
        s_consec_fails = 0;
    } else {
        s_consec_fails++;
    }
    return ok ? ESP_OK : ESP_FAIL;
}

/* 总线解锁：SCL 打 10 个脉冲复位从设备状态机（GPIO 始终在手，无需动驱动） */
static void bus_recovery(void)
{
    ESP_LOGW(TAG, "I2C 连续失败 %d 次，SCL 打脉冲解锁 + 传感器软复位", s_consec_fails);
    for (int i = 0; i < 10; i++) {
        scl_low();
        ets_delay_us(5);
        scl_high();
        ets_delay_us(5);
    }
    i2c_stop();

    /* 软复位 + 重写全部配置 */
    write_reg(REG_MODE_CONFIG, 0x40);
    vTaskDelay(pdMS_TO_TICKS(20));
    write_reg(REG_FIFO_CONFIG, 0x0F);
    write_reg(REG_SPO2_CONFIG, 0x26);      /* 100Hz/215µs/4096nA */
    write_reg(REG_LED1_PA, LED_CURRENT);
    write_reg(REG_LED2_PA, LED_CURRENT);
    write_reg(REG_MLED_CTRL1, 0x21);
    write_reg(REG_INTR_ENABLE_1, 0x00);
    write_reg(REG_INTR_ENABLE_2, 0x00);
    write_reg(REG_MODE_CONFIG, 0x03);

    s_consec_fails = 0;
    ESP_LOGW(TAG, "总线恢复完成");
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
    gpio_config(&io);
    /* 关键 1：gpio_config 后输出锁存默认 0，开漏输出会把 SDA/SCL 主动拉低——
     * 必须立即置高释放总线（空闲电平恢复上拉） */
    sda_high();
    scl_high();
    /* 关键 2：IDF 5.2 的 gpio_config 对输出模式会关闭 IO_MUX 输入使能（FUN_IE），
     * 导致 gpio_get_level 恒读 0（ACK 假阳性）。必须显式重开输入。 */
    gpio_ll_input_enable(&GPIO, PIN_SDA);
    gpio_ll_input_enable(&GPIO, PIN_SCL);

    /* 上电复位 */
    write_reg(REG_MODE_CONFIG, 0x40);
    vTaskDelay(pdMS_TO_TICKS(20));

    /* 芯片 ID 校验 */
    if (read_reg(REG_PART_ID, &s_part_id) != ESP_OK || s_part_id != EXPECTED_PART_ID) {
        ESP_LOGE(TAG, "PartID=0x%02x，期望 0x%02x", s_part_id, EXPECTED_PART_ID);
        return ESP_ERR_INVALID_RESPONSE;
    }

    /* ---- 配置顺序：先全部配好，最后写 MODE 启动采样 ---- */
    write_reg(REG_FIFO_CONFIG, 0x0F);      /* 采样平均关闭、滚动关闭、满水位 15 */
    write_reg(REG_SPO2_CONFIG, 0x26);      /* 4096nA、100Hz、脉宽 215µs */
    write_reg(REG_LED1_PA, LED_CURRENT);
    write_reg(REG_LED2_PA, LED_CURRENT);
    write_reg(REG_MLED_CTRL1, 0x21);       /* 关键：SLOT1=RED、SLOT2=IR，不复位不采样 */
    write_reg(REG_INTR_ENABLE_1, 0x00);
    write_reg(REG_INTR_ENABLE_2, 0x00);
    write_reg(REG_MODE_CONFIG, 0x03);      /* 启动 SpO2 模式 */

    /* 清 FIFO：读指针只能靠读 FIFO_DATA 自动推进，读空为止 */
    uint8_t drain[6];
    int drain_count = 0;
    while (drain_count < 32) {
        uint8_t rd = 0, wr = 0;
        if (read_reg(REG_FIFO_RD_PTR, &rd) != ESP_OK ||
            read_reg(REG_FIFO_WR_PTR, &wr) != ESP_OK) {
            break;
        }
        if (((wr - rd) & 0x1F) == 0) {
            break;
        }
        if (read_regs(REG_FIFO_DATA, drain, sizeof(drain)) != ESP_OK) {
            break;
        }
        drain_count++;
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
    /* 连续失败判定总线卡死 → 恢复 */
    if (s_consec_fails >= I2C_FAIL_RECOVER) {
        bus_recovery();
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
