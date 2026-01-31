#!/usr/bin/env bash
set -o errexit

pip install -r ttac_project/requirements.txt
python ttac_project/manage.py collectstatic --noinput
python ttac_project/manage.py migrate
