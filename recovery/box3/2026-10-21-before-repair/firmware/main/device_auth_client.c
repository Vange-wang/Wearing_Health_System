#include "device_auth_client.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "credential_store.h"
#include "mbedtls/md.h"
#include "mbedtls/hkdf.h"
#include "mbedtls/platform_util.h"


#define DEVICE_TOKEN_CAPACITY 256

typedef esp_err_t (*device_token_loader_fn)(char *out, size_t capacity);

static char s_device_token[DEVICE_TOKEN_CAPACITY];
static bool s_device_token_ready;
static uint8_t s_discovery_key[32];
static bool s_discovery_ready;
static bool derive_discovery(const char *token,uint8_t key[32])
{
    static const uint8_t salt[]="voicebridge/box-discovery/hkdf-sha256/v1";
    static const uint8_t info[]="voicebridge/box-discovery/hmac-key/v1";
    size_t n=strlen(token);
    if(!n || n>255 || token[0]==' ' || token[n-1]==' ')return false;
    for(size_t i=0;i<n;i++)if((unsigned char)token[i]<0x20 || (unsigned char)token[i]>0x7e || token[i]==',')return false;
    return mbedtls_hkdf(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),salt,sizeof(salt)-1,
        (const uint8_t *)token,n,info,sizeof(info)-1,key,32)==0;
}
bool device_auth_discovery_ready(void){return s_discovery_ready;}
static bool scoped_mac(const uint8_t key[32],const uint8_t *prefix,size_t size,uint8_t out[32])
{
    if(!prefix || !out || (size!=26 && size!=50) ||
        memcmp(prefix,"VBXD0001",8) || prefix[8]!=1 || prefix[9]!=(size==26?1:2))return false;
    return mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),key,32,prefix,size,out)==0;
}
bool device_auth_discovery_mac(const uint8_t *prefix,size_t size,uint8_t out[32])
{return s_discovery_ready && scoped_mac(s_discovery_key,prefix,size,out);}
bool device_auth_discovery_verify(const uint8_t prefix[50],const uint8_t mac[32])
{
    uint8_t expected[32];
    if(!mac || !device_auth_discovery_mac(prefix,50,expected))return false;
    volatile unsigned difference=0;
    for(unsigned i=0;i<32;i++)difference|=expected[i]^mac[i];
    mbedtls_platform_zeroize(expected,sizeof(expected));return difference==0;
}


static esp_err_t device_auth_client_init_with_loader(device_token_loader_fn loader)
{
    memset(s_device_token, 0, sizeof(s_device_token));
    mbedtls_platform_zeroize(s_discovery_key,sizeof(s_discovery_key));s_discovery_ready=false;
    s_device_token_ready = false;
    if (loader == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = loader(s_device_token, sizeof(s_device_token));
    if (err != ESP_OK || s_device_token[0] == '\0') {
        memset(s_device_token, 0, sizeof(s_device_token));
        return err == ESP_OK ? ESP_ERR_NOT_FOUND : err;
    }
    s_device_token[sizeof(s_device_token) - 1] = '\0';
    s_device_token_ready = true;
    s_discovery_ready=derive_discovery(s_device_token,s_discovery_key);
    return ESP_OK;
}


esp_err_t device_auth_client_init(void)
{
    return device_auth_client_init_with_loader(credential_store_load_device_token);
}


esp_err_t add_device_auth_header(esp_http_client_handle_t client)
{
    if (!s_device_token_ready || s_device_token[0] == '\0') {
        return ESP_ERR_NOT_FOUND;
    }
    if (client == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    return esp_http_client_set_header(client, "X-Device-Token", s_device_token);
}


esp_err_t open_authenticated_http(esp_http_client_handle_t client, int write_len)
{
    esp_err_t err = add_device_auth_header(client);
    if (err != ESP_OK) {
        return err;
    }
    return esp_http_client_open(client, write_len);
}


#ifdef DEVICE_AUTH_CLIENT_SELF_TEST
static esp_err_t missing_token_loader(char *out, size_t capacity)
{
    if (out != NULL && capacity > 0) {
        out[0] = '\0';
    }
    return ESP_ERR_NOT_FOUND;
}


esp_err_t device_auth_client_selftest(void)
{
    if (device_auth_client_init_with_loader(missing_token_loader) !=
        ESP_ERR_NOT_FOUND) {
        return ESP_FAIL;
    }

    /* A sentinel handle is safe here only if the missing-token gate prevents open. */
    esp_http_client_handle_t sentinel = (esp_http_client_handle_t)(uintptr_t)1;
    if (open_authenticated_http(sentinel, 0) != ESP_ERR_NOT_FOUND) {
        return ESP_FAIL;
    }
    return ESP_OK;
}
#endif

#ifdef DEVICE_AUTH_DISCOVERY_SELF_TEST
bool device_auth_discovery_selftest(void)
{
    static const uint8_t expected_key[32]={0xab,0x89,0x66,0x2a,0x40,0x26,0x24,0xd3,0x46,0x97,0xbe,0x8e,0x47,0xcc,0x77,0x6b,0xda,0xd3,0x45,0xde,0x89,0x24,0x87,0x8c,0xbb,0x6f,0xfa,0x13,0xfd,0xf9,0xe2,0xed};
    static const uint8_t request_prefix[26]={0x56,0x42,0x58,0x44,0x30,0x30,0x30,0x31,0x01,0x01,0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0a,0x0b,0x0c,0x0d,0x0e,0x0f};
    static const uint8_t request_mac[32]={0x59,0x64,0xce,0xa5,0x84,0x13,0xac,0x9d,0xd6,0xd5,0x4b,0x87,0x04,0xbd,0xf7,0x76,0x89,0x4f,0xca,0xd4,0x25,0xb2,0x10,0xa4,0x4a,0x13,0x24,0x8d,0x3f,0x10,0x22,0x00};
    static const uint8_t response_prefix[50]={0x56,0x42,0x58,0x44,0x30,0x30,0x30,0x31,0x01,0x02,0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0a,0x0b,0x0c,0x0d,0x0e,0x0f,0xc0,0xa8,0x01,0x71,0x22,0x06,0xf0,0xf1,0xf2,0xf3,0xf4,0xf5,0xf6,0xf7,0xf8,0xf9,0xfa,0xfb,0xfc,0xfd,0xfe,0xff,0x00,0x78};
    static const uint8_t response_mac[32]={0xbc,0xb2,0xe3,0x8b,0xe7,0x4c,0xf8,0xd7,0x59,0x3a,0x0c,0xbe,0x42,0x6c,0xa7,0xd4,0x4c,0x20,0x4c,0xb3,0xa0,0x08,0xcd,0xff,0x81,0xe4,0xae,0x55,0x74,0x6a,0x50,0x25};
    static const uint8_t rfc_okm[32]={0x3c,0xb2,0x5f,0x25,0xfa,0xac,0xd5,0x7a,0x90,0x43,0x4f,0x64,0xd0,0x36,0x2f,0x2a,0x2d,0x2d,0x0a,0x90,0xcf,0x1a,0x5a,0x4c,0x5d,0xb0,0x2d,0x56,0xec,0xc4,0xc5,0xbf};
    uint8_t key[32],mac[32],ikm[22],salt[13],info[10];
    memset(ikm,0x0b,sizeof(ikm));
    for(unsigned i=0;i<13;i++)salt[i]=(uint8_t)i;
    for(unsigned i=0;i<10;i++)info[i]=(uint8_t)(0xf0+i);
    bool ok=mbedtls_hkdf(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),salt,sizeof(salt),ikm,sizeof(ikm),info,sizeof(info),key,32)==0 && !memcmp(key,rfc_okm,32);
    ok=ok && derive_discovery("PUBLIC-ONLY box3 vector 01",key) && !memcmp(key,expected_key,32);
    ok=ok && scoped_mac(key,request_prefix,sizeof(request_prefix),mac) && !memcmp(mac,request_mac,32);
    ok=ok && scoped_mac(key,response_prefix,sizeof(response_prefix),mac) && !memcmp(mac,response_mac,32);
    ok=ok && !derive_discovery(" bad",key) && !derive_discovery("bad ",key) && !derive_discovery("a,b",key);
    ok=ok && !derive_discovery("\xc3\xa9",key) && !derive_discovery("",key);
    mbedtls_platform_zeroize(key,sizeof(key));mbedtls_platform_zeroize(mac,sizeof(mac));return ok;
}
#endif
