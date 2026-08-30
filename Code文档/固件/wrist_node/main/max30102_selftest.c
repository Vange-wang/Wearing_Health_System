#include "max30102.h"

#ifdef MAX30102_SELF_TEST

esp_err_t max30102_selftest(void)
{
    return max30102_fault_injection_selftest();
}

#endif
