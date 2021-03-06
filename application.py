#! /usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Turku University (2018) Department of Future Technologies
# Foresail-1 / PATE Monitor / Middleware (PMAPI)
# uWSGI entry point
#
# application.py - Jani Tammi <jasata@utu.fi>
#
#   0.1.0   2018.10.11  Initial version.
#   0.1.1   2018.10.14  Fixed the version output in the logging message.
#   0.1.2   2018.10.23  Entire Flash application moved into this file.
#   0.1.3   2018.10.29  Print lapsed ms in @app.teardown_request debug message.
#
#
# Code in this file gets executed ONLY ONCE, when the uWSGI is started.
# The only exceptions are @app.before_request and @app.teardown_request
# decorated functions, which are executed once per HTTP Request.
#
#
# uWSGI configuration (uwsgi.ini) specifies flask app directory to be
# ("chdir = /srv/nginx-root/") and that the 'application' is to be found
# in this module ("module = application"  =>  'application.py').
#
# If the execution directory ("chdir" in uwsgi.ini) changes,
# this file has to be updated accordingly.
#
import os
import time
import logging
import sqlite3

from logging.handlers       import RotatingFileHandler
from logging                import Formatter
from flask                  import Flask
from flask                  import g


# For some reason, if Flask() is given 'debug=True',
# uWSGI cannot find the application and startup fails.
#
# The behavior of relative paths in config files can be flipped
# between “relative to the application root” (the default) to 
# “relative to instance folder” via the instance_relative_config
# switch to the application constructor:
app = Flask(
    __name__,
    instance_relative_config=True
)


#
# PATE Monitor JSON API implementation version number (integer)
#
try:
    with open('APIVERSION') as version_file:
        for line in version_file:
            try:
                apiversion = int(line.strip())
                break
            except:
                pass
except:
    # File issues
    apiversion = -1
finally:
    setattr(app, 'apiversion', apiversion)

#
# PATE Monitor Middleware application version
#
try:
    with open('APPVERSION') as vfile:
        for line in vfile:
            appversion = line.strip()
            if not len(appversion):
                continue
            if appversion[0:1] == '#':
                # Its a comment
                continue
            else:
                appversion = appversion.split()[0]
                break
except:
    # File issues
    appversion = "0.0.0"
finally:
    setattr(app, 'appversion', appversion)


#
# Flask Application Configuration
#
# With Flask 0.8 a new attribute was introduced: Flask.instance_path.
# It refers to a new concept called the “instance folder”. The instance
# folder is designed to not be under version control and be deployment
# specific. It’s the perfect place to drop things that either change at
# runtime or configuration files.
#
# Config file is in '${app dir}/instance/' when the
# Flask application instance has been created with;
# Flask(.., instance_relative_config=True)
#
app.config.from_pyfile('application.conf')


#
# Logging
#
handler = RotatingFileHandler(
    app.config.get('LOG_FILENAME', 'application.log'),
    maxBytes    = 1000000,
    backupCount = 1
)
handler.setFormatter(
    Formatter(
        '%(asctime)s %(levelname)s: %(message)s '
        '[in %(pathname)s:%(lineno)d]'
    )
)
app.logger.addHandler(handler)
# Setting is given as a string, which needs to be converted into
# the integer value that logger module uses. Default to DEBUG.
# Using getattr() with default instead of logging.getLevelName()
# because the logger function has a nasty feature of returning
# invalid values as string "Level " + <invalid value>.
# We definitely need a valid fallback value for invalid arguments.
app.logger.setLevel(
    getattr(
        logging,
        str(app.config.get('LOG_LEVEL', 'DEBUG')),
        logging.DEBUG
    )
)
app.logger.info(
    "Logging enabled for level {} ({})"
    .format(
        logging.getLevelName(app.logger.getEffectiveLevel()),
        app.logger.getEffectiveLevel()
    )
)



#
# This logging happens only once, when uWSGI daemon starts
#
app.logger.info(
    "\n"
    "==============================================================\n"
    "PATE Monitor REST API (PMAPI) Flask application started\n"
    "Turku University (2018) Department of Future Technologies\n"
    "Version {}, Jani Tammi <jasata@utu.fi>\n"
    "REST API version {}\n"
    .format(app.appversion, app.apiversion)
)


#
# Check certain important configuration values
#
if not app.config.get('COMMAND_TIMEOUT', None):
    app.logger.warning(
        "COMMAND_TIMEOUT not defined in application.conf! Defaulting to 1 second..."
    )
    app.config['COMMAND_TIMEOUT'] = 1.0

if not app.config.get('COMMAND_POLL_INTERVAL', None):
    app.logger.warning(
        "COMMAND_POLL_INTERVAL not defined in application.conf! Defaulting to 0.2 seconds..."
    )
    app.config['COMMAND_POLL_INTERVAL'] = 1.0




###############################################################################
#
# REQUEST HANDLING
#
###############################################################################

@app.before_request
def before_request():
    """
    Opens a new database connection if there is none yet for the
    current application context.
    """
    #
    # Start timing
    #
    # Because not all requests are REST JSON API requests, .teardown_request()
    # cannot be tasked to inject timing information. Each REST API call handler
    # must do this themselves.
    #
    g.t_real_start = time.perf_counter()
    g.t_cpu_start  = time.process_time()
    app.logger.debug("@app.before_request")

    #
    # Ensure database connection
    #
    if not hasattr(g, 'db'):
        g.db = sqlite3.connect(
            app.config.get('SQLITE3_DATABASE_FILE', 'pmapi.sqlite3')
        )
        cursor = g.db.cursor()
        cursor.execute("PRAGMA foreign_keys = 1")

    return

#
# Routes in 'routes.py'
#
import routes

#
# Executed each time application context tears down
# (request ends)
#
@app.teardown_request
def teardown_request(error):
    """
    Closes the database again at the end of the request.
    """
    app.logger.debug(
        "@app.teardown_request ({:.1f}ms)"
        .format((time.perf_counter() - g.t_real_start) * 1000)
    )
    if hasattr(g, 'db'):
        g.db.close()


# EOF
