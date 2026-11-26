# Temporary M2.0 (#50) probe project: builds pinned upstream whisper.cpp plus the
# synthetic ggml device diagnostic in one tree. Not production code.
cmake_minimum_required(VERSION 3.20)
project(whisper_probe C CXX)

if(NOT WHISPER_SRC)
  message(FATAL_ERROR "Pass -DWHISPER_SRC=<path to upstream whisper.cpp checkout>")
endif()

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES ON CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(WHISPER_CURL OFF CACHE BOOL "" FORCE)

add_subdirectory(${WHISPER_SRC} whisper)

add_executable(ggml-diag devices.cpp)
target_link_libraries(ggml-diag PRIVATE ggml)
target_compile_features(ggml-diag PRIVATE cxx_std_17)
