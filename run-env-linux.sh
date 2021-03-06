#!/bin/bash

export QGIS_PREFIX_PATH=/usr/local/qgis-master
export QGIS_PATH=QGIS_PREFIX_PATH
export LD_LIBRARY_PATH=${QGIS_PREFIX_PATH}/lib
export PYTHONPATH=${QGIS_PREFIX_PATH}/share/qgis/python:${PYTHONPATH}

echo "QGIS PATH: $QGIS_PREFIX_PATH"
export QGIS_DEBUG=0
export QGIS_LOG_FILE=/tmp/inasafe/realtime/logs/qgis.log
export QGIS_DEBUG_FILE=/tmp/inasafe/realtime/logs/qgis-debug.log


export INASAFE_WORK_DIR=/tmp/quake
export INASAFE_POPULATION_PATH=`pwd`/realtime/fixtures/exposure/population.tif
export INASAFE_LOCALE=id

echo "This script is intended to be sourced to set up your shell to"
echo "use a QGIS 2.0 built in $QGIS_PREFIX_PATH"
echo
echo "To use it do:" 
echo "source $0"
echo
echo "Then use the make file supplied here e.g. make guitest"
