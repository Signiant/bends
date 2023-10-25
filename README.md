# BENDS (Build Error Notification Dispatch System)

A tool that checks the status of the most recently executed scheduled pipeline of Bitbucket repositories associated with 
services listed in the Datadog Service Catalog.

An AWS CloudFormation template is included in this repository to facilitate the automation of this script's execution 
through the use of an AWS Lambda function.

## Requirements

Alongside **Python 3.11+**, the following packages must be installed to run this tool:
- boto3
- requirements

Additionally, you need to have both AWS CLI & AWS SAM CLI installed and configured. The following guides provide 
detailed instructions on how to do so:
1. [Install or update the latest version of the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
2. [Set up the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-quickstart.html)
3. [Installing the AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)

## Setup

Whether you plan to run the script locally or to deploy a Lambda function, you must do these four things:

1. Clone this repository.
2. Create app pass/keys with the following scopes:
   - Bitbucket Pass: repository, pipeline
   - Datadog Key: apm_service_catalog_read
3. Create a Slack webhook that can access the channels you would like the script to post to
4. Set environment variables:
   1. BB_APP_PASS=_<bitbucket-app-pass>_
   2. BB_USER_ID=_<bitbucket-user-id>_
   3. DD_API_KEY=_<datadog-api-key>_
   4. DD_APP_KEY=_<datadog-app-key>_
   5. SLACK_WEBHOOK_URL=_<slack-webhook-url>_
5. Set values specific to your use case for the two global variables found at the top of bob_the_builder.py.
6. Depending on how the different team channels are named in Slack, you may need to modify the post_to_slack function
to post to the correct channels.

### Local Execution

1. Install dependencies:  
`python -m pip install -r requirements.txt`
2. In the same directory as the script, execute the provided command:  
`python -m bends`

#### Run Examples

- Run script and process all services in the Datadog Service Catalog  
`python bends.py`
- Run script and process all services in the Datadog Service Catalog, but ignore services with Bitbucket repositories 
whose names begin with "media"  
`python bends.py --override media*`
- Run script and process only repos listed in data.json  
`python bends.py --data`
- Run script with more detailed logs on repositories managed by specific teams  
`python bob_the_builder.py --teams bits mercury breakfast-club --verbose`

### Deployment (Using SAM CLI)

1. Set a schedule in cron format as well as a description for the Lambda event in the template.yaml file.
2. Build the .aws-sam directory:  
`sam build`
3. Deploy one of two versions of this Lambda:  
   - To deploy the dev version (unscheduled):  
   `sam deploy --stack-name TEXT --s3-bucket TEXT --s3-prefix TEXT --region TEXT --parameter-overrides 
   "AppName=bob-the-builder-dev EnvName=dev DryRun=true BBAPPPASS=$BB_APP_PASS BBUSERID=$BB_USER_ID DDAPIKEY=$DD_API_KEY 
   DDAPPKEY=$DD_APP_KEY SLACKWEBHOOKURL=$SLACK_WEBHOOK_URL"`
   - To deploy the prod version (scheduled):  
   `sam deploy --stack-name TEXT --s3-bucket TEXT --s3-prefix TEXT --region TEXT --parameter-overrides 
   "AppName=bob-the-builder-prod EnvName=prod BBAPPPASS=$BB_APP_PASS BBUSERID=$BB_USER_ID DDAPIKEY=$DD_API_KEY 
   DDAPPKEY=$DD_APP_KEY SLACKWEBHOOKURL=$SLACK_WEBHOOK_URL"`
4. (Optional) *Create an AWS SAM CLI config file to skip entering the arguments in the previous step every time you want to 
deploy. Learn more about that 
[here](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-config.html).*