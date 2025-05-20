#!/usr/bin/env bash

. hooks/molecule.rc

TOX_TEST="${1}"

if [ -f "./collections.yml" ]
then
  ${current_dir}/hooks/manage_collections.py --scenario ${TOX_SCENARIO:-default}
  echo ""
fi

tox ${TOX_OPTS} -- molecule ${TOX_TEST} ${TOX_ARGS}
