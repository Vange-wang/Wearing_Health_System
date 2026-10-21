cmake_minimum_required(VERSION 3.5)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

set(EXTRA_COMPONENT_DIRS
    D:/box3-cdx-v2-20261016-candidate/components
    )

add_compile_options(-fdiagnostics-color=always)

set(PROJECT_VER "box3-ack-caption-20261015-b1")
project(voice_agent)
