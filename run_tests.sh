#!/usr/bin/env bash
set -e
mkdir -p reports
python -m pytest --html=reports/test_report.html --self-contained-html --cov=src --cov-report=html:reports/coverage_html --cov-report=term-missing
