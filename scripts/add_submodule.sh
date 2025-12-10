#!/usr/bin/env bash

REPO=$1
read -p "Add ${REPO} as submodule? " -n 1 -r
#echo    # (optional) move to a new line
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    # handle exits from shell or function but don't exit interactive shell
    [[ "$0" = "$BASH_SOURCE" ]] && exit 1 || return 1 
fi

set -x

# clone repository as submodule
git submodule add git@github.com:munch-group/${REPO}.git
# initialize it
git submodule init ${REPO} # initialize it
# and pull the current state of the submodule repo
git submodule update ${REPO} # and pull the current state of the submodule repo
# track .gitmodules
git add .gitmodules ${REPO} && git commit -m "Added ${REPO} as submodule" && git push # track .gitmodules
# checkout main 
cd ${REPO} && git checkout main && cd ..  