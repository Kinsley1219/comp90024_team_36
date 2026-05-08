#!/bin/sh
# COMP90024 Team 36
# Fission package build script for Reddit harvester
# Follows the same pattern as teacher's reference implementation
# SRC_PKG: directory containing source files and requirements.txt
# DEPLOY_PKG: target directory for the deployment package

pip3 install -r ${SRC_PKG}/requirements.txt -t ${SRC_PKG} && cp -r ${SRC_PKG} ${DEPLOY_PKG}