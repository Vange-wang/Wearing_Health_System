#include "discovery_protocol.h"
#include "device_auth_client.h"
#include <string.h>
static uint32_t u32(const uint8_t p[4])
{return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
bool paired_discovery_request(const uint8_t nonce[16],uint8_t out[58])
{
    if(!nonce || !out)return false;
    memcpy(out,"VBXD0001",8);out[8]=1;out[9]=1;memcpy(out+10,nonce,16);
    return device_auth_discovery_mac(out,26,out+26);
}
bool paired_discovery_response(const uint8_t *data,size_t size,const uint8_t source[4],uint16_t source_port,
    const uint8_t nonce[16],const uint8_t local[4],const uint8_t mask[4],paired_discovery_reply_t *out)
{
    if(!data || !source || !nonce || !local || !mask || !out || size!=82 || memcmp(data,"VBXD0001",8) ||
        data[8]!=1 || data[9]!=2 || memcmp(data+10,nonce,16))return false;
    if(!device_auth_discovery_verify(data,data+50))return false;
    if(source_port!=8711 || memcmp(source,data+26,4) || data[30]!=0x22 || data[31]!=0x06)return false;
    uint16_t ttl=((uint16_t)data[48]<<8)|data[49];
    uint32_t ip=u32(source),own=u32(local),netmask=u32(mask),network=own&netmask;
    if(ttl<30 || ttl>120 || !source[0] || source[0]==127 || (source[0]==169 && source[1]==254) || source[0]>=224 ||
        ip==own || (ip&netmask)!=network || ip==network || ip==(network|~netmask))return false;
    memcpy(out->ipv4,source,4);memcpy(out->instance,data+32,16);out->ttl=ttl;return true;
}
