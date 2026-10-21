#include "health_json.h"
#include "cJSON.h"
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

health_json_result_t health_json_status(const char *body,size_t length)
{
    if(!body||length==SIZE_MAX||memchr(body,0,length)!=NULL)return HEALTH_JSON_INVALID;
    cJSON *root=cJSON_ParseWithLengthOpts(body,length+1U,NULL,1);
    if(!cJSON_IsObject(root)){cJSON_Delete(root);return HEALTH_JSON_INVALID;}
    cJSON *protocol=cJSON_GetObjectItemCaseSensitive(root,"protocol");
    if(cJSON_IsString(protocol) && strcmp(protocol->valuestring,"voice-v2")==0) {
        bool ready=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(root,"process_alive")) &&
            cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(root,"ready"));
        cJSON_Delete(root);return ready?HEALTH_JSON_READY:HEALTH_JSON_NOT_READY;
    }
    cJSON *tts=cJSON_GetObjectItemCaseSensitive(root,"tts");
    cJSON *probe=cJSON_GetObjectItemCaseSensitive(tts,"last_probe_ok");
    cJSON *status=cJSON_GetObjectItemCaseSensitive(root,"status");
    cJSON *asr=cJSON_GetObjectItemCaseSensitive(root,"asr");
    cJSON *auth=cJSON_GetObjectItemCaseSensitive(root,"device_auth");
    int ok=cJSON_IsTrue(probe)&&cJSON_IsString(status)&&strcmp(status->valuestring,"ok")==0&&
      cJSON_IsString(asr)&&strcmp(asr->valuestring,"ready")==0&&
      cJSON_IsString(auth)&&strcmp(auth->valuestring,"ok")==0;
    cJSON_Delete(root);return ok?HEALTH_JSON_READY:HEALTH_JSON_NOT_READY;
}
