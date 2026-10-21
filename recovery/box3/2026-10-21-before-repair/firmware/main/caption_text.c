#include "caption_text.h"
#include <stdint.h>
#include <string.h>

static size_t character(const char *text,size_t remaining)
{
    if (!remaining) return 0;
    uint8_t c=(uint8_t)text[0];unsigned more;uint32_t cp,minimum;
    if(c==0)return 0;
    if(c<0x80)return 1;
    if(c>=0xc2&&c<=0xdf){cp=c&31;more=1;minimum=0x80;}
    else if(c>=0xe0&&c<=0xef){cp=c&15;more=2;minimum=0x800;}
    else if(c>=0xf0&&c<=0xf4){cp=c&7;more=3;minimum=0x10000;}
    else return 0;
    if(more>=remaining)return 0;
    unsigned size=more+1;
    for(unsigned i=1;i<size;i++){c=(uint8_t)text[i];if((c&0xc0)!=0x80)return 0;cp=(cp<<6)|(c&63);}
    if(cp<minimum||cp>0x10ffff||(cp>=0xd800&&cp<=0xdfff))return 0;
    return size;
}

bool caption_text_valid(const char *text,size_t length)
{
    if(text==NULL)return false;
    for(size_t cursor=0;cursor<length;){size_t n=character(text+cursor,length-cursor);if(!n)return false;cursor+=n;}
    return true;
}

bool caption_text_page(const char *text,size_t length,size_t *offset,char *out,size_t capacity)
{
    if(!text||!offset||!out||!capacity||*offset>length)return false;
    size_t cursor=*offset,used=0;unsigned row=0,column=0;
    while(cursor<length&&row<3){
        size_t n=character(text+cursor,length-cursor);if(!n)return false;
        if(column==18&&text[cursor]!='\n'){
            if(used+1>=capacity)return false;
            out[used++]='\n';row++;column=0;if(row==3)break;
        }
        if(n>=capacity-used)return false;
        memcpy(out+used,text+cursor,n);used+=n;
        if(text[cursor]=='\n'){row++;column=0;}else column++;
        cursor+=n;
    }
    out[used]=0;*offset=cursor;return true;
}
