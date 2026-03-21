cmake_minimum_required(VERSION 3.13 FATAL_ERROR)

project(genesis_sprite_viewer CXX C)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 COMPONENTS Core Gui Widgets REQUIRED)

# Sources
set(SOURCES
    plugin.cpp
    GenesisSpriteViewer.cpp
    GenesisSpriteViewer.h
)

add_library(${PROJECT_NAME} SHARED ${SOURCES})

# Binary Ninja API
if (NOT BN_API_BUILD_EXAMPLES AND NOT BN_INTERNAL_BUILD)
    find_path(
        BN_API_PATH
        NAMES binaryninjaapi.h
        HINTS ../../../bn-api
              ../../binaryninja-api
              $ENV{BN_API_PATH}
        REQUIRED
    )
    add_subdirectory(${BN_API_PATH} api)
endif()

target_link_libraries(${PROJECT_NAME}
    binaryninjaui
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
)

set_target_properties(${PROJECT_NAME} PROPERTIES
    CXX_STANDARD 17
    CXX_VISIBILITY_PRESET hidden
    CXX_STANDARD_REQUIRED ON
    VISIBILITY_INLINES_HIDDEN ON
    POSITION_INDEPENDENT_CODE ON
)

# Install to BN plugins directory
if (NOT BN_INTERNAL_BUILD)
    bn_install_plugin(${PROJECT_NAME})
endif()
