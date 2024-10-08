Name:           cron-homedirs
Version:        0.7.2
Release:        20
Summary:        Relays cron periodic executables into accessible home directories

License:        GPLv2
URL:            https://github.com/Osndok/cron-homedirs

BuildArch:      noarch

Requires:       calc
Requires:       cronie
Requires:       cronie-anacron
Requires:       util-linux

%description
Allows periodic crontab entries to be specified within any user home directory
(rather than only in /etc/cron.*). A side effect is that home directories that
come & go (such as, encrypted home directories) are silently skipped if they
are unavailable, without having to over-specify such a test for every crontab
entry that is so far removed from the original home directory.

If used with auto-mounted home directories on a multi-machine setup, this is
expected to do TERRIBLE THINGS!!!! So don't do that!


%install
rm -rf $RPM_BUILD_ROOT
mkdir  $RPM_BUILD_ROOT
cd     $RPM_BUILD_ROOT

mkdir -p etc/cron.{d,hourly,weekly,monthly,daily}
mkdir -p usr/libexec

# ===========================================================================

cat    -> ./etc/cron.hourly/homedirs <<"EOF"
exec /usr/libexec/cron-homedirs-regular hourly
EOF

# ===========================================================================

cat    -> ./etc/cron.monthly/homedirs <<"EOF"
exec /usr/libexec/cron-homedirs-regular monthly
EOF
# ===========================================================================

cat    -> ./etc/cron.weekly/homedirs <<"EOF"
exec /usr/libexec/cron-homedirs-regular weekly
EOF


# ===========================================================================

cat    -> ./etc/cron.daily/homedirs <<"EOF"
exec /usr/libexec/cron-homedirs-regular daily
EOF

# ===========================================================================

cat -> ./etc/cron.d/homedirs <<"EOF"
* * * * * root /usr/libexec/cron-homedirs-minute
EOF

# ===========================================================================

cat    -> ./usr/libexec/cron-homedirs-subs <<"EOF"
function process()
{
	local USER="$1"
	local FILE="$2"

	local FAIL="${FILE}.fail"
	local LOCK="${FILE}.lock"
	local LOG="${FILE}.log"

	# We should make sure that at least the files written inside the 'su' command are user-owned
	# BEFORE we ask for them to be written to...
	# TODO: Security issue? Could this 'chown' be abused with symlinks, or something?
	chown --quiet "$FAIL" "$LOCK" "$LOG" || true

	if su $USER --command "flock --close --wait 5 --verbose $LOCK $FILE >> $LOG 2>&1" 2> "$FAIL" < /dev/null
	then
		rm -f "$FAIL" >> "$LOG" 2>&1
	else
		CODE=$?
		echo "$(date +"%Y-%m-%d %H:%M") - exit status $CODE" | tee $FAIL >> "$LOG"
	fi

	# Is this still needed, now that we have a chown before we run the command?
	# TODO: Security issue? Could this 'chown' be abused with symlinks, or something?
	chown "$USER" "${FILE}".*
}

function looks_like_user_home_dir()
{
	local USER_DIR="$1"
	[ -n "$USER_DIR" ] && [ "$USER_DIR" != "/" ]
}

function looks_like_user_cron_dir()
{
	local USER_DIR="$1"
	[ -d "$USER_DIR" ]
}

function user_can_execute()
{
	local USER="$1"
	local FILE="$2"

	# BUG: not safe for spaces, etc.
	su "$USER" -c "test -x $FILE"
}
EOF

# ===========================================================================

cat    -> ./usr/libexec/cron-homedirs-minute <<"EOF"
#!/bin/bash
#
# Called every minute, to check and see what actions might be accomplished
# for the less-reliable (and lossy) minute-modulous directories.
#

. /usr/libexec/cron-homedirs-subs

cd /

MINUTE_NUMBER=$(calc "floor($(date +%%s)/60)")
HOUR_NUMBER=$(calc "floor($(date +'%s')/3600)")

TMP=$(mktemp /tmp/cron-homedirs-minute.XXXXXXXX)

function execute_directory_scripts()
{
	local CRON_DIR="$1"

	if looks_like_user_cron_dir "$CRON_DIR"
	then
		ls "$CRON_DIR" | while read FILE_BASE
		do
			FILE="$CRON_DIR/$FILE_BASE"
			if user_can_execute "$USER" "$FILE"
			then
				# NB: the /dev/null keeps it from consuming our stdin
				process "$USER" "$FILE" < /dev/null
			fi
		done
	fi
}

#BUG: some directories are assigned to multiple usernames.. don't use those for this purpose!
cut -d: -f1,6 /etc/passwd | sort | tr : ' ' > $TMP

while read USER USER_DIR
do

	if looks_like_user_home_dir "$USER_DIR" && test -d "$USER_DIR/etc" -o test -d "$USER_DIR/.local/etc"
	then
		
		for FILENAME in $USER_DIR/etc/* $USER_DIR/.local/etc/*
		do
			# e.g. ~/etc/cron.30min, ~/etc/cron.30m
			PERIOD=$(basename "$FILENAME" | sed -nE 's/cron\.([0-9]+)mi?n?s?$/\1/p')

			if [ -z "$PERIOD" ]
			then
				continue
			fi
		
			# Check if MINUTE_NUMBER is divisible by PERIOD
			if [ $(calc "${MINUTE_NUMBER}%${PERIOD}") == 0 ]
			then
				execute_directory_scripts "${FILENAME}"
			fi
		done


		# We launch our hourly stuff at the 07 minute to help avoid the N-o-clock rush.
		if [ "$(date +%%M)" == "07" ]
		then
			# e.g. ~/etc/cron.9pm
			COMMON_TIME=$(date +"%%l%%P" | tr -d ' ')
			execute_directory_scripts ${USER_DIR}/etc/cron.${COMMON_TIME}
			execute_directory_scripts ${USER_DIR}/.local/etc/cron.${COMMON_TIME}
				
			for FILENAME in $USER_DIR/etc/* $USER_DIR/.local/etc/*
			do
				# e.g. ~/etc/cron.3h, ~/etc/cron.2hrs
				PERIOD=$(basename "$FILENAME" | sed -nE 's/cron\.([0-9]+)hr?s?$/\1/p')

				if [ -z "$PERIOD" ]
				then
					continue
				fi
			
				# Check if HOUR_NUMBER is divisible by PERIOD
				if [ $(calc "${HOUR_NUMBER}%${PERIOD}") == 0 ]
				then
					execute_directory_scripts "${FILENAME}"
				fi
			done

		fi
	fi
done < $TMP

rm -f $TMP
EOF

# ===========================================================================

touch     ./usr/libexec/cron-homedirs-regular
chmod 755 ./usr/libexec/cron-homedirs-regular
cat    -> ./usr/libexec/cron-homedirs-regular <<"EOF"
#!/bin/bash
#
# Searches for available/mounted/decrypted crontab entries
# INSIDE A USERS DIRECTORY that matches this pattern:
#
# ~/etc/cron.${1}/some-executable-file
# 
# ...and runs any/all of them that are marked as executable
# AS THAT USER with diagnostic output directed to a similarly
# named file (".log" appended to it).
#

. /usr/libexec/cron-homedirs-subs

# by unsetting SHELL, we will default to the user's preferred shell...
# which may be 'nologin'...
unset SHELL
set -vx
set -eu

cd /

PERIOD="$1"

TMP=$(mktemp /tmp/cron-homedirs-${PERIOD}.XXXXXXXX)
TMP2=$(mktemp /tmp/cron-homedirs-${PERIOD}.XXXXXXXX)

#BUG: some directories are assigned to multiple usernames.. don't use those for this purpose!
cut -d: -f1,6 /etc/passwd | sort | tr : ' ' > $TMP

while read USER USER_DIR
do

	if looks_like_user_home_dir "$USER_DIR"
	then

		CRON_DIR=${USER_DIR}/etc/cron.${PERIOD}

		if looks_like_user_cron_dir "$CRON_DIR"
		then
			ls "$CRON_DIR" > $TMP2
			while read FILE_BASE
			do
				FILE="$CRON_DIR/$FILE_BASE"
				if user_can_execute "$USER" "$FILE"
				then
					# NB: the /dev/null keeps it from consuming our stdin
					process "$USER" "$FILE" < /dev/null
				fi
			done < $TMP2
		fi

		CRON_DIR=${USER_DIR}/.local/etc/cron.${PERIOD}

		if looks_like_user_cron_dir "$CRON_DIR"
		then
			ls "$CRON_DIR" > $TMP2
			while read FILE_BASE
			do
				FILE="$CRON_DIR/$FILE_BASE"
				if user_can_execute "$USER" "$FILE"
				then
					# NB: the /dev/null keeps it from consuming our stdin
					process "$USER" "$FILE" < /dev/null
				fi
			done < $TMP2
		fi

	fi
done < $TMP

rm -f $TMP $TMP2

EOF

# ===========================================================================

%files
%attr(644, root, root) /etc/cron.d/homedirs
%attr(755, root, root) /etc/cron.hourly/homedirs
%attr(755, root, root) /etc/cron.weekly/homedirs
%attr(755, root, root) /etc/cron.monthly/homedirs
%attr(755, root, root) /etc/cron.daily/homedirs
%attr(644, root, root) /usr/libexec/cron-homedirs-subs
%attr(755, root, root) /usr/libexec/cron-homedirs-minute
%attr(755, root, root) /usr/libexec/cron-homedirs-regular

