#!/usr/bin/env python
"""
API Frontend for our mobile apps to use, served by one of our many devops teams.
Sends HASH to Backend secure API to verify the caller is one of the many UnicornRentals teams
Returns HASH that mobile apps use to verify the message AND server API version are legitimate
HASH changes when files in codebase change for security.
Wouldnt want competitors scraping our FULL backend API, or man in middle attacks against our apps
Probably better way to do this, but for now this will do.
"""

__author__ = 'Inigo Montoya (inigo.montoya@unicornrentals.click)'
__vcs_id__ = '4e927e1a0a8608bfc58e9ea52d91f2cf'
__version__ = 'b19b0ccbe0069f8efd563e55c3ea69a4'

from flask import Flask, request
from flask_restful import Resource, Api
import os, json, logging
import requests
import boto3

#Secure Hash code - it works out our secret by hashing all the source files
#A valid hash needs unchanged files in /unicorn_descriptions and secrethash.py, and the correct version numbers in app.py
from secrethash import hasher

# Set Unicorn Rentals backend API URL to proxy API requests too
# We use AWS SSM Parameter Store, as is much easier and clearer than using ENVARS
client = boto3.client('ssm')
response = client.get_parameter(Name='BACKEND_API')
BACKEND_API = response['Parameter']['Value']
print "Backend set to: {}".format(BACKEND_API)

#Make sure we can find unicorn files
CODE_DIR = os.getenv('CODE_DIR')
if not CODE_DIR:
    CODE_DIR = './'

app = Flask(__name__)
api = Api(app)

#Lets try and log Flask / Requests to Cloudwatch logs
logging.basicConfig(level=logging.INFO)

def get_secret():
    #Compute secure hash to use as shared secret with backend API
    secretmaker = hasher()
    secretmaker.generate(CODE_DIR+'unicorn_descriptions/*')
    secretmaker.generate(CODE_DIR+'secrethash.py')
    secretmaker.generate_text(__version__)
    secretmaker.generate_text(__vcs_id__)
    return secretmaker.hexdigest.strip()

class HealthCheck(Resource):
    def get(self):
        #This just lets things know that this proxy is alive
        return {'status': 'OK'}

class Unicorn(Resource):
    def get(self):
        #Return List of Unicorns - You may find some cool unicorns to check out
        #Unsecured API - this call works even if we don't have current code (and thus a valid secret hash)
        req = requests.get(BACKEND_API+'/unicorn')
        return json.loads(req.text), req.status_code

class Unicorns(Resource):
    def get(self, unicorn_id):
        #Get details of specific Unicorn
        #Compute a secret hash so the backend will reply, and the caller knows its a genuine response
        #This is how our teams performance is measured - if this doent work we will not have a job long
        shared_secret = get_secret()
        headers = {'x-unicorn-api-secret': shared_secret}
        req = requests.get(BACKEND_API+'/unicorns/'+unicorn_id, headers=headers)
        return json.loads(req.text), req.status_code, {'x-unicorn-api-secret': shared_secret}

    def post(self, unicorn_id):
        #Give a unicorn a treat by sending him a json "snack"
        #Also needs a "teamid"
        #API secured by secrets the AWS unicorns have
        data = request.get_json()
        req = requests.post(BACKEND_API+'/unicorns/'+unicorn_id, json={'snack':data['snack'],'teamid':data['teamid']})
        return req.json(), req.status_code


api.add_resource(HealthCheck,'/healthcheck','/')
api.add_resource(Unicorn, '/unicorn')
api.add_resource(Unicorns, '/unicorns/<string:unicorn_id>')


if __name__ == '__main__':
    #If running in prod - log to xray and CWL
    try:
        import watchtower
        handler = watchtower.CloudWatchLogHandler(log_group='CICDApiProxy',)
        app.logger.addHandler(handler)
        logging.getLogger("werkzeug").addHandler(handler)
        logging.getLogger('aws_xray_sdk').addHandler(handler)
        logging.getLogger('requests').addHandler(handler)
    except:
        print "Couldn't start CW Logging"

    #Lets try to use AWS X-ray for metrics / logging if available to us
    try:
        from aws_xray_sdk.core import xray_recorder
        from aws_xray_sdk.ext.flask.middleware import XRayMiddleware
        xray_recorder.configure(service='CICDApiProxy')
        xray_recorder.configure(context_missing='LOG_ERROR')
        XRayMiddleware(app, xray_recorder)
        from aws_xray_sdk.core import patch
        patch(('requests'))
    except:
        print 'Failed to import X-ray'
    app.run(host='0.0.0.0')
