#! /usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Turku University (2018) Department of Future Technologies
# Foresail-1 / PATE Monitor / Middleware (PMAPI)
# API module
#
# api/__init__.py - Jani Tammi <jasata@utu.fi>
#
#   0.1.0   2018.10.11  Initial version.
#   0.2.0   2018.10.23  Content moved to top-level application.py.
#   0.2.1   2018.10.25  Added API Exception classes.
#   0.3.0   2018.10.29  Enhanced Flask.Response creation.
#   0.4.0   2018.11.04  Changes for CSV streaming support.
#   0.4.1   2018.11.05  Documentation update.
#
#
#   Module for PATE Monitor Resource Objects/Classes and API
#
#       API layout (endpoints/routes) are created in '/routes.py' file.
#       This directory contains the code that implements the interaction
#       between REST API calls and the database.
#
#   This file
#
#       api.response()
#
#       Turns a  ??? tuple (<data dictionary>, <HTTP response code>)
#       into a Flask.Response object (which is the expected return type
#       for route handles).
#
#   Resource Objects/Classes
#
#       Objects may implement following public JSON CRUD functions:
#       (C) .post()     POST (create entity) -> (code:int, payload:dict):tuple      code: 200, payload: {'id' : <id:int>}
#       (R) .get()      GET (fetch-type)     -> (code:int, payload:dict):tuple      code: 200, payload: {'data' : [<item:dict>]}
#       (R) .search()   GET (search-type)    -> (code:int, payload:dict):tuple      code: 200, payload: {'data' : [<item:dict>]}
#       (U) .patch()    PATCH, PUT (update)  -> (code:int, payload:dict):tuple
#       (D) .delete()   DELETE               -> (code:int, None):tuple
#
#       All JSON functions MUST return a tuple!
#
#       DataObjects may also implement a CSV extraction method by means of
#       .query() -> SQLite.Cursor method and
#       api.stream_result_as_csv(result:SQLite.Cursor)
#       Implementation belongs into the 'route.py':
#
#       @app.route('/csv/classifieddata', methods=['GET'])
#       def csv_classifieddata():
#           log_request(request)
#           try:
#               from api.ClassifiedData import ClassifiedData
#               return api.stream_result_as_csv(ClassifiedData(request).query())
#           except Exception as e:
#               app.logger.exception(
#                   "CSV generation failure! " + str(e)
#               )
#               raise
#
#
#   DataObject code (code that interacts with database) is written as separate
#   modules (Python source files) in this directory. 
# Classes model data by providing CRUD interactions and returning
# data as dictionaries (or list of dictionaries, for searches)
# - or they raise ApiExceptions (see this file) when necessary.
#

import time
import json

from flask          import request
from flask          import g
from application    import app


###############################################################################
#
# DataObject class (SQLite3 utilities)
#
#   Every API class should derive itself from this class.
#
#   DataObject.__init__(cursor, table: str, exclude: list)
#       Initializes the DataObject for 'table' by reading in column metadata.
#       NOTE: You should not exclude primary keys. Intended for obsolete
#             columns that are not yet purged from the database.
#
#   DataObject().columns: list
#       All columns the 'table' that was given for the initialiaztion,
#       except the columns that were specified in 'exclude' list during
#       initialization.
#
#   DataObject().keys: list
#       List of primary key columns in the <table>.
#
#   DataObject().select_columns(exclude: list) -> str
#       Returns a string for SELECT clause where special formatting is
#       applied to datatypes that need it (namely, TIMESTAMP and DATETIME).
#       Optional exclude list may be supplied for columns that are not
#       needed among selected items.
#
#   DataObject().where_condition(column: str) -> str
#       Parse needed conversions and casts according to the datatype.
#
#   NOTE:
#   SQLite natively supports only the types TEXT, INTEGER, REAL, BLOB and NULL.
#
class DataObject(list):
    # class Column:
    #     __slots__ = ('name', 'datatype', 'nullable', 'default', 'primarykey')
    #     def __init__(
    #         self,
    #         name,
    #         datatype,
    #         nullable,
    #         default,
    #         primarykey
    #     ):
    #         self.name       = name
    #         self.datatype   = datatype
    #         self.nullable   = nullable
    #         self.default    = default
    #         self.primarykey = primarykey

    class DotDict(dict):
        """dot.notation access to dictionary attributes"""
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__
        __delattr__ = dict.__delitem__
        def __missing__(self, key):
            """Return None if non-existing key is accessed"""
            return None
        def __str__(self):
            return self.getattr('name', '(null)')

    def __init__(self, cursor, table, exclude = []):
        # pragma_table_info() columns:
        # cid           Column ID number
        # name          Column name
        # type          INTEGER | DATETIME | ...
        # notnull       1 = NOT NULL, 0 = NULL
        # dflt_value    Default value
        # pk            1 = PRIMARY KEY, 0 = not
        cursor.execute("SELECT * FROM pragma_table_info('{}')".format(table))
        for row in cursor:
            if row[1] not in exclude:
                self.append(
                    self.DotDict(
                        name        = row[1],
                        datatype    = row[2],
                        nullable    = True if row[3] == 0 else False,
                        default     = row[4],
                        primarykey  = True if row[5] == 1 else False
                    )
                )
        # Get active session_id or None
        app.logger.critical("Fix to REAL session mgmt!!")
        cursor.execute("SELECT max(id) FROM testing_session")
        self.session_id = cursor.fetchone()[0]


    @property
    def columns(self):
        """Returns a list of column names."""
        return [col.name for col in self]


    @property
    def primarykeys(self):
        """Returns a list of primary key columns."""
        return [col.name for col in self if col.primarykey]


    def missing_columns(self, columns):
        """Returns False if provided list of column names contain any that do not exist in the database table."""
        if not columns:
            return []
        existing = self.columns
        missing = []
        for column in columns:
            if column not in existing:
                missing.append(column)
        return missing


    def get_column_objects(
        self,
        include = [],
        exclude = [],
        include_primarykeys = True
    ):
        """Get a list of column objects.

        All arguments are optional.
        include - list of column names to include
        exclude - list of column names to exlude
        include_primarykeys - True | False if primary keys are to be included

        If optional 'include' list can be provided, the result list to specified. However, if 'include_primary_keys' is True, the parsed string will always contain also the primary key columns - even if they are not defined in the 'include' and excluded in the 'exclude' list.
        
        If a column is defined in both 'include' and 'exclude', exclude list will take precedence and column is not included. Only exception to this rule are primary key columns (when 'include_primarykeys' is True)."""
        # Purge primary keys from exclude list, if 'include_primarykeys'
        if exclude and include_primarykeys:
            exclude = [col for col in exclude if col not in self.primarykeys]
        # Compile list of column objects/dicts
        if not include:
            # empty 'include' equals ALL fields (except 'excluded')
            flist = [col for col in self if col.name not in exclude]
        else:
            flist = []
            for col in self:
                app.logger.debug(col.name)
                if col.primarykey and include_primarykeys:
                    # Forced inclusion for pk
                    flist.append(col)
                elif col.name in include and col.name not in exclude:
                    flist.append(col)
        return flist


    def get_column_names(
        self,
        include = [],
        exclude = [],
        include_primarykeys = True
    ):
        """See get_column_objects() for documentation. This function returns a list of names (strings)."""
        lst = self.get_column_objects(include, exclude, include_primarykeys)
        return [c.name for c in lst]


    def select_typecast(self, column):
        """Take column object argument and return string representation of the column name, with datatype specific typecasting, if necessary."""
        if column.datatype == 'TIMESTAMP':
            return "CAST(strftime('%s', {0}) as integer) AS {0}".format(column.name)
        elif column.datatype == 'DATETIME':
            return "datetime({0}) AS {0}".format(column.name)
        else:
            return column.name


    def select_columns(
        self,
        include = [],
        exclude = [],
        include_primarykeys = True
    ):
        """Provide datatype specific formatting for SQL queries. Optional 'include' list can be provided, limiting the parsing to specified. However, if 'include_primary_keys' is True, the parsed string will always contain also the primary key columns - even if they are not defined in the 'include' and excluded in the 'exclude' list.
        
        If a column is defined in both 'include' and 'exclude', exclude list will take precedence and column is not included. Only exception to this rule are primary key columns (when 'include_primarykeys' is True)."""
        # Purge primary keys from exclude list, if 'include_primarykeys'
        if exclude and include_primarykeys:
            exclude = [col for col in exclude if col not in self.primarykeys]
        # Compile list of column objects/dicts
        if not include:
            # empty 'include' equals ALL fields (except 'excluded')
            flist = [col for col in self if col.name not in exclude]
        else:
            flist = []
            for col in self:
                if col.primarykey and include_primarykeys:
                    flist.append(col)
                elif col.name in include and col.name not in exclude:
                    flist.append(col)

        slist = []
        # NOTE: Fractional timestamp (Warning - fractional inaccuracy!)
        # SELECT (julianday(timestamp) - 2440587.5) * 86400.0
        # 1541695244 (exact) becomes: 1541695244.00001
        for col in flist:
            if col.datatype == 'TIMESTAMP':
                slist.append(
                    "CAST(strftime('%s', {0}) as integer) AS {0}"
                    .format(col.name)
                )
            elif col.datatype == 'DATETIME':
                slist.append(
                    "datetime({0}) AS {0}"
                    .format(col.name)
                )
            else:
                slist.append(col.name)
        return ", ".join(slist)


    def where_condition(self, column):
        """Return formatting for condition column based on datatype."""
        col = None
        for c in self:
            if c.name == column:
                col = c
                break
        if not col:
            raise ValueError("Non-existent column specified")
        # return suitable conversion
        if col.datatype == 'TIMESTAMP':
            return "CAST(strftime('%s', {}) as integer)".format(col.name)
        elif col.datatype == 'DATETIME':
            return "datetime({})".format(col.name)
        else:
            return "{}".format(col.name)


    def __str__(self):
        return "\n".join([str(c) for c in self])




#
# __make_response(code, payload)
# API internal / Generate Flask.Response from HTTP response code and data
# dictionary.
#
# Argument
#   code_payload        (code:int, payload:dict):tuple
#
def __make_response(code, payload):
    """Generate Flask.Response from provided response code and dictionary."""
    # Paranoia check
    assert(isinstance(payload, dict))
    assert(isinstance(code, int))

    try:
        #
        # Common api element for JSON responses
        #
        payload['api'] = {
            'version'   : app.apiversion,
            't_cpu'     : time.process_time() - g.t_cpu_start,
            't_real'    : time.perf_counter() - g.t_real_start
        }
        # NOTE: PLEASE remove 'indent' and 'sort_keys' when developing is done!!!
        # 'default=str' is useful setting to handle obscure data, leave it.
        # (for example; "datetime.timedelta(31) is not JSON serializable")
        # https://stackoverflow.com/questions/7907596/json-dumps-vs-flask-jsonify
        t = time.perf_counter()
        #payload = json.dumps(payload, indent=4, sort_keys=True, default=str)
        payload = json.dumps(payload, default=str)
        app.logger.debug("REMOVE SORT! json.dumps(): {:.1f}ms".format((time.perf_counter() - t) * 1000))

        response = app.response_class(
            response    = payload,
            status      = code,
            mimetype    = 'application/json'
        )
        allow = [method for method in request.url_rule.methods if method not in ('HEAD', 'OPTIONS')]
        response.headers['Allow']        = ", ".join(allow)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        # VERY IMPORTANT! Do NOT re-raise the exception!
        app.logger.exception("Internal __make_response() error!")
        # We will try to offer dict instead of Flask.Response...
        return app.response_class(
            response = "api.__make_response() Internal Error: {}".format(str(e)),
            status   = 500
        )



#
# api.response((code:int, payload:dict):tuple) -> Flask.Response
# JSON Flask.Response create function for Flask route handlers
#
def response(response_tuple):
    """Create Flask.Response from provided (code:int, data:dict):tuple."""
    return __make_response(response_tuple[0], response_tuple[1])


#
# api.exception_response(ApiException | Exception)
# Exception handling function for Flask route handlers
#
#   Generate payload dictionary from the ApiException or Exception object
#   and return through __make_response(), which generates the Flask.Response
#   object.
#
def exception_response(ex):
    """Generate JSON payload from ApiException or Exception object."""
    if not ex:
        app.logger.error("Function received argument: None!")
        return __make_response(
            500,
            {
                "error"   : "Unknown",
                "details" : "api.exception_response() received: None!"
            }
        )
    # 
    try:
        if isinstance(ex, Exception):
            # Member variable '.ApiException' reveals the type
            if getattr(ex, 'ApiException', None):
                app.logger.error(
                    "ApiException: '{}'"
                    .format(str(ex))
                )
                response_code = ex.code
                response_payload = ex.to_dict()
            else:
                # Unexpected error, log trace by using logger.exception()
                app.logger.exception(str(ex))
                from traceback import format_exception
                e = format_exception(type(ex), ex, ex.__traceback__)
                response_payload = {
                    "error" : e[-1],
                    "trace" : "".join(e[1:-1])
                }
                response_code = 500
            return __make_response(response_code, response_payload)
        else:
            return __make_response(
                500,
                {
                    "error"     : "Uknown",
                    "details"   : "api.exception_response() received unsupported argument",
                    "type"      : type(ex)
                }
            )
    except Exception as e:
        app.logger.exception("Internal Error!")
        return __make_response(
            500,
            {
                "error"     : "Internal Error",
                "details"   : "api.exception_response() internal failure!"
            }
        )


#
# UNDER TESTING (Seems to fail before streaming out 3 GB)
# https://stackoverflow.com/questions/28011341/create-and-download-a-csv-file-from-a-flask-view
#
# Takes queried cursor and streams it out as CSV file
def stream_result_as_csv(cursor):
    """Takes one argument, SQLite3 query result, which is streamed out as CSV file."""
    import io       # for StringIO
    import csv
    # Generator object for the Response() to use
    def generate(cursor):
        data = io.StringIO()
        writer = csv.writer(data)

        # Yield header
        writer.writerow(
            (key[0] for key in cursor.description)
        )
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)

        # Yeild data
        for row in cursor:
            writer.writerow(row)
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    from werkzeug.datastructures    import Headers
    from werkzeug.wrappers          import Response
    from flask                      import stream_with_context
    #
    # Response header
    #
    headers = Headers()
    headers.set(
        'Content-Disposition',
        'attachment',
        filename = time.strftime(
            "%Y-%m-%d %H.%M.%S.csv",
            time.localtime(time.time())
        )
    )

    # RFC 7111 (wich updates RFC 4180) states that the MIME type for
    # CSV is "text/csv". (Google Chrome can shut the hell up).
    #
    # Stream the response using the local generate() -generator function.
    return Response(
        stream_with_context(generate(cursor)),
        mimetype='text/csv',
        headers=headers
    )



###############################################################################
#
#
# API Exception classes
#
#
#   These JSON API exceptions allow DataObjects to reply with specification
#   defined responses for various exceptional conditions, simply by raising
#   the appropriate exception. Route handlers (in 'route.py') catch these
#   exceptions and route them into api.exception_response() function (found
#   in this file). Exceptions are then converted into HTTP responses.
#

class ApiException(Exception):

    # Used to identify objects based on ApiException and its subclasses.
    # Because, ...I don't know how a better way to do this.
    ApiException = True

    def __init__(
        self,
        message = "Unspecified API Error",  # as in Exception
        details = None                      # Any additional details
    ):
        """Initialize API Exception instance"""
        super().__init__(message)
        self.details = details

    def to_dict(self):
        """Return values of each fields of an jsonapi error"""
        error_dict = {'message' : str(self)}
        # Do not include 'code', because that is used as the response code
        if getattr(self, 'details', None):
            error_dict.update({'details' : getattr(self, 'details')})
        return error_dict



#
# Client side errors (4xx)
#

# 404 Not Found
class NotFound(ApiException):
    """Identified item was not found in the database."""
    def __init__(
        self,
        message = "Entity not found!",
        details = None
    ):
        super().__init__(message, details)
        self.code = 404


# 405 Method Not Allowed
# Combination of URI and method is not supported
class MethodNotAllowed(ApiException):
    """Request method is not supported."""
    def __init__(
        self,
        message = "Requested method is not supported!",
        details = None
    ):
        super().__init__(message, details)
        self.code = 405


# 406 Not Acceptable
class InvalidArgument(ApiException):
    """Provided argument(s) are invalid!"""
    def __init__(
        self,
        message = "Provided argument(s) are invalid!",
        details = None
    ):
        super().__init__(message, details)
        self.code = 406


# 409 Conflict
class Conflict(ApiException):
    """Unique/PK,FK or other constraint violation."""
    def __init__(
        self,
        message = "Unique, primary key, foreign key or other constraint violation!",
        details = None
    ):
        super().__init__(message, details)
        self.code = 409


#
# Server side errors (5xx)
#

# 500 Internal Server Error
class Timeout(ApiException):
    """Processing/polling exceeded allowed timeout."""
    def __init__(
        self,
        message = "Processing/polling exceeded allowed timeout!",
        details = None
    ):
        super().__init__(message, details)
        self.code = 500


# 500 Internal Server Error
class InternalError(ApiException):
    """All other internal processing erros, except timeouts."""
    def __init__(
        self,
        message = "Unspecified internal processing error!",
        details = None
    ):
        super().__init__(message, details)
        self.code = 500


# 501 Not Implemented
# Route exists, implementation does not
# For request to something that is not planned, return 405
class NotImplemented(ApiException):
    """Requested functionality is not yet implemented."""
    def __init__(
        self,
        message = "Requested functionality is not yet implemented.",
        details = None
    ):
        super().__init__(message, details)
        self.code = 501


# EOF
