#include "mic4_layout.h"
static int16_t halfword(const uint8_t *p)
{return (int16_t)((uint16_t)p[0]|((uint16_t)p[1]<<8));}
bool mic4_layout_valid(const mic4_layout_t *m)
{
    if(!m || !m->verified)return false;
    uint8_t ids[4]={m->mic1,m->mic2,m->reference,m->unused};unsigned seen=0;
    for(unsigned i=0;i<4;i++){if(ids[i]>=4 || (seen&(1U<<ids[i])))return false;seen|=1U<<ids[i];}
    return seen==15;
}
bool mic4_unpack(const uint8_t *raw,size_t bytes,const mic4_layout_t *m,int16_t *pairs,size_t capacity)
{
    if(!raw || !pairs || bytes%8 || bytes/8>capacity || !mic4_layout_valid(m))return false;
    for(size_t i=0;i<bytes/8;i++){
        const uint8_t *p=raw+i*8;
        pairs[2*i]=(int16_t)(((int32_t)halfword(p+2*m->mic1)+halfword(p+2*m->mic2))/2);
        pairs[2*i+1]=halfword(p+2*m->reference);
    }
    return true;
}
bool mic4_measure(const uint8_t *raw,size_t bytes,mic4_stats_t *stats)
{
    if(!raw || !stats || bytes%8)return false;
    for(size_t i=0;i<bytes/8;i++)for(unsigned c=0;c<4;c++){
        int32_t v=halfword(raw+i*8+c*2);uint32_t mag=v<0?(uint32_t)-v:(uint32_t)v;
        stats->energy[c]+=(uint64_t)((int64_t)v*v);
        if(mag>stats->peak[c])stats->peak[c]=(uint16_t)mag;
        if(mag>=32760)stats->clipped[c]++;
    }
    stats->samples+=bytes/8;return true;
}
