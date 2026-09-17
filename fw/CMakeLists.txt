# Host build of the ECU firmware.
#
# The point of a host build is that the control path -- decoder,
# scheduler, torque model, fuel, monitor -- is ordinary C with no
# peripheral access, so it can be compiled and tested on a PC. The only
# thing the target build adds is a different HAL.
#
#   cmake -S fw -B build/fw && cmake --build build/fw && ctest --test-dir build/fw
cmake_minimum_required(VERSION 3.16)
project(torquetune_fw C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(-Wall -Wextra -Werror)

# Firmware sources: no HAL, so nothing here can touch hardware by accident.
add_library(tqcore STATIC
    src/decoder.c
    src/sched.c
    src/model.c
    src/fuel.c
    src/monitor.c
    src/ecu.c
    src/cal.c
    src/proto.c
)
target_include_directories(tqcore PUBLIC include)
target_link_libraries(tqcore PUBLIC m)

add_library(tqhal_host STATIC hal/hal_host.c)
target_include_directories(tqhal_host PUBLIC include hal)
target_link_libraries(tqhal_host PUBLIC tqcore)

# The firmware running on a PC, speaking the tuner protocol on stdio.
# tests/test_serial_link.py drives the real tuner against this.
add_executable(ecu_host tools/ecu_host.c)
target_link_libraries(ecu_host PRIVATE tqcore)

enable_testing()

set(TQ_TESTS test_decoder test_sched test_model test_fuel test_monitor test_ecu
             test_proto test_di)
foreach(t ${TQ_TESTS})
    add_executable(${t} tests/${t}.c)
    target_include_directories(${t} PRIVATE tests)
    target_link_libraries(${t} PRIVATE tqcore tqhal_host)
    # the model test reads the golden file produced from the Python model
    add_test(NAME ${t}
             COMMAND ${t} ${CMAKE_CURRENT_SOURCE_DIR}/tests/data/golden.txt)
endforeach()
