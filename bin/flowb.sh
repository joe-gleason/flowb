#!/usr/bin/env bash

#===========================================================
# CLI
#===========================================================

opt_build_project=$GERRIT_PROJECT
opt_build_branch=$GERRIT_BRANCH
opt_build_flow="default"
opt_dir_start="$(pwd)"

while getopts ":af:p:b:d:-:" opt; do
   case $opt in
      - )   # for long options
         case "$OPTARG" in 
            version )
               exit 0
            ;;
            * ) 
               echo "------------------------------"
               echo "ERROR:Invalid option [$OPTARG]"
               echo "------------------------------"
               exit 1
            ;;
         esac
      ;;
      p )
         opt_build_project=$OPTARG
      ;;
      b )
         opt_build_branch=$OPTARG
      ;;
      f )
         opt_build_flow=$OPTARG
      ;;
      d )
         opt_dir_start=$OPTARG
      ;;
      \? ) 
         echo "------------------------------"
         echo "ERROR:Invalid option [$OPTARG]"
         echo "------------------------------"
         exit 1
      ;;
   esac
done

shift $(($OPTIND - 1))

#===========================================================
# Setup
#===========================================================

whoami="$(readlink -f $0)"
toolName="$(basename $whoami)"
binDir="$(dirname $whoami)"
versionDir="$(dirname $binDir)"
version="$(basename $versionDir)"
libDir="$versionDir/lib"
profileDir="$versionDir/profiles"
currDir="$(pwd)"

export FLOWB_ORIG_DIR=$currDir

# Move to start directory
#
echo "Starting in directory [$opt_dir_start]"
cd $opt_dir_start

export FLOWB_START_DIR=$opt_dir_start

# Default some variables if they are not defined
#
if [ -z "$JENKINS_HOME" ];then
   export JENKINS_HOME=/nis/asic/jenkins-ws/jenkins
   echo "Defaulting JENKINS_HOME=$JENKINS_HOME"
fi

# PROJECT
#  If running in gerrit project will be $GERRIT_PROJECT
#  Otherwise we will detect via a git command
if [ "${opt_build_project:-unset}" = unset ]; then
   opt_build_project=`git remote show origin | grep "Fetch URL:" | sed "s-^.*/\(.*\)-\1-" | xargs -i basename {}`
   opt_build_project=${opt_build_project%%.*}
   echo "Detecting project as [$opt_build_project]"
fi

# BRANCH
#  If running in gerrit branch will be $GERRIT_BRANCH
#  Otherwise we will detect via a git call
if [ "${opt_build_branch:-unset}" = unset ]; then
   opt_build_branch=`git rev-parse --abbrev-ref HEAD`
   echo "Detecting branch as [$opt_build_branch]"
fi

# FLOW
if [ "${opt_build_flow:=default}" = default ]; then
   echo "Detecting flow as [$opt_build_flow]"
fi

#===========================================================
# PROFILES
#===========================================================

# hpn_jenkins is where the current jenkins builder exists
#   if that is our project then lets run things locally from the repo
#   this allows us to upload changes to the repo and have those run instead
#
if [ $opt_build_project = "hpn_jenkins" ]; then 
   echo "We are currently in hpn_jenkins, run local files to pick up changes"
   profileDir="$currDir/bin/tools/jenkins_builder/$version/profiles"
   binDir="$currDir/bin/tools/jenkins_builder/$version/bin"
fi


# Flow builder profile
#  This gets us access to other scripts/tools
profile=$profileDir/profile.flowb
if [ ! -e $profile ]; then
   echo "-ERROR- Profile [$profile] does not exist"
   exit 1
fi
echo "Sourcing profile [$profile]"
source $profile

# Depending on the PROJECT we source the necessary profile
#  profile.hpn_rosewood
#  profile.hpn_jenkins
#  profile.<tbd>
#
profile=$profileDir/profile.$opt_build_project
if [ -e $profile ]; then
   echo "Sourcing profile [$profile]"
   source $profile
else
   echo "WARNING - no profile named [$profile]"
fi

if [ $opt_build_project = "hpn_jenkins" ]; then
   export PATH=$binDir:$PATH
else
   export PATH=$PATH:$binDir
fi

#===========================================================
# Run build process
#===========================================================
echo "Launching Build Process for [$opt_build_project] [$opt_build_branch] [$opt_build_flow]"
echo ""
$binDir/flowb -p $opt_build_project -b $opt_build_branch -f $opt_build_flow
