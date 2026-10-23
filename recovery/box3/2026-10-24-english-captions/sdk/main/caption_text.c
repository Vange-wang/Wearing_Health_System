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

static uint32_t codepoint(const char *s, size_t n)
{
    uint32_t cp=(uint8_t)s[0];
    if(n>1) {cp&=(1U<<(7-n))-1;for(size_t i=1;i<n;i++)cp=(cp<<6)|((uint8_t)s[i]&63);}
    return cp;
}

bool caption_text_line(const char *text,size_t length,bool finished,unsigned pixels,
                       caption_glyph_width_t width,void *context,char *out,
                       size_t capacity,caption_line_t *line)
{
    if(!text||!out||!capacity||!line||!width||pixels<16)return false;
    *line=(caption_line_t){0};out[0]=0;
    size_t i=0,used=0,break_in=0,break_out=0;
    unsigned x=0;bool in_word=false;
    while(i<length) {
        size_t n=character(text+i,length-i);if(!n)return false;
        uint32_t cp=codepoint(text+i,n);
        if(cp=='\r' && i+n==length && !finished) {out[used]=0;return true;}
        if(cp=='\n'||cp=='\r') {
            size_t consume=n;
            if(cp=='\r'&&i+n<length&&text[i+n]=='\n')consume++;
            line->consumed=i+consume;line->ready=true;out[used]=0;return true;
        }
        bool space=cp==' '||cp=='\t';
        bool cjk=(cp>=0x2e80&&cp<=0x9fff)||(cp>=0xff00&&cp<=0xffef);
        unsigned w=width(space?' ':cp,context);
        char fallback='?';const char *glyph=text+i;size_t bytes=n;
        if(space){glyph=" ";bytes=1;}
        if(!w){w=width('?',context);glyph=&fallback;bytes=1;}
        /* Asset contract: 8/16 px. Never accept zero-width/unbounded output. */
        if(w<8||w>pixels)return false;
        if(x+w>pixels) {
            if(break_in){
                used=break_out;line->consumed=break_in;
                /* Keep CJK closing punctuation with the preceding glyph. */
                if(break_in==i && (cp==0x3002||cp==0xff0c||cp==0xff01||cp==0xff1f||cp==0xff1b||cp==0xff1a||cp==0x3001||cp==0x3009||cp==0x300b||cp==0xff09)) {
                    size_t prev=i-1;while(prev && ((uint8_t)text[prev]&0xc0)==0x80)prev--;
                    size_t pn=i-prev;uint32_t pc=codepoint(text+prev,pn);
                    size_t bytes_back=width(pc,context)?pn:1;
                    if(!prev||bytes_back>used)return false;
                    used-=bytes_back;line->consumed=prev;
                }
            }
            else {
                /* Long unbroken word only: reserve a visible ASCII continuation. */
                unsigned mark=width('>',context);
                if(mark<8||mark>pixels)return false;
                while(used && x+mark>pixels) {
                    size_t prev=i-1;while(prev && ((uint8_t)text[prev]&0xc0)==0x80)prev--;
                    size_t pn=i-prev;uint32_t pc=codepoint(text+prev,pn);
                    unsigned pw=width(pc,context);if(!pw)pw=width('?',context);
                    size_t output_bytes=width(pc,context)?pn:1;
                    if(output_bytes>used)return false;
                    used-=output_bytes;x-=pw;i=prev;
                }
                if(!i||used+1>=capacity)return false;
                out[used++]='>';line->continuation=true;line->consumed=i;
            }
            line->ready=true;out[used]=0;return true;
        }
        if(used+bytes>=capacity)return false;
        memcpy(out+used,glyph,bytes);used+=bytes;x+=w;i+=n;
        if(space||cjk){break_in=i;break_out=used;}
        if(cjk){line->cjk_chars++;in_word=false;}
        else if(space)in_word=false;
        else if(!in_word){line->latin_words++;in_word=true;}
    }
    if(finished) {line->consumed=i;line->ready=i!=0;}
    else if(break_in)used=break_out;
    else used=0;
    out[used]=0;
    return true;
}
