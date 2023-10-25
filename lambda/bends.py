import argparse
import re
from json import JSONDecodeError
from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.service_definition_api import ServiceDefinitionApi
from datadog_api_client.v2.model.service_definition_schema_versions import ServiceDefinitionSchemaVersions
from datetime import datetime, timedelta, timezone
import logging
import os
import requests
import sys
import json

logging.basicConfig(format="%(asctime)s - %(levelname)8s: %(message)s", stream=sys.stdout)
logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

OVERALL_SUMMARY_RECIPIENT = ""  # Set to the name of the team receiving the overall summary
WORKSPACE = ""  # Set Bitbucket workspace name to be used in HTTP requests


def post_to_slack(team: str, blocks: dict) -> None:
    """
    Post summary blocks to slack

    :param team: the team that will be receiving the notification
    :param blocks: the summary blocks to be posted
    """
    try:
        slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
        if not slack_webhook_url:
            logging.error("SLACK_WEBHOOK_URL environment variable is required for Slack notifications.")
            sys.exit(1)
        payload = {"blocks": blocks, "channel": f"team-{team}-bots"}
        headers = {"Content-Type": "application/json"}
        response = requests.post(slack_webhook_url, data=json.dumps(payload), headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.exception(f"Error posting to Slack: {e}")


def post_team_summaries_to_slack(summaries: dict, max_blocks_per_message=10) -> None:
    """
    Post a series of team summary blocks to slack

    :param summaries: the summaries to be posted
    :param max_blocks_per_message: the maximum number of blocks per message
    """
    logging.info("Posting summaries to slack...")

    # Split the summary blocks into smaller chunks(Slack is truncating the payload if we send entire summary)
    for team in summaries.keys():
        for i in range(0, len(summaries[team]), max_blocks_per_message):
            chunked_summary_blocks = summaries[team][i:i + max_blocks_per_message]
            post_to_slack(team, chunked_summary_blocks)


def generate_overall_summary(teams_recent_builds: dict) -> list:
    """
        Generate Slack message blocks for overall summary

        :param teams_recent_builds: a dict containing lists of failed and successful builds sorted by team
        :return: a dict of Slack message blocks
        """
    logging.info("Generating overall summary...")
    summary = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Build Error Notification Dispatch System"
            }
        }
    ]

    for team in teams_recent_builds.keys():
        summary.extend(
            [
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Team: *{team}*"
                    }
                }
            ]
        )
        if len(teams_recent_builds[team]["Succeeded"]) == 0 and len(teams_recent_builds[team]["Failed"]) == 0:
            summary.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "No scheduled builds in repositories not in development."
                    }
                }
            )
            continue

        successful_builds = len(teams_recent_builds[team]["Succeeded"])

        text = "*Successful Builds*\n"
        if successful_builds == 1:
            text += f">*{successful_builds} repository* had a successful build."
        else:
            text += f">*{successful_builds} repositories* had successful builds."

        summary.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            }
        )

        text = "*Failed Builds*\n"
        if len(teams_recent_builds[team]["Failed"]) != 0:
            for build in teams_recent_builds[team]["Failed"]:
                text += ">• <" + build["RepositoryUrl"] + "|" + build["RepositorySlug"] + ">\n"
        else:
            text += ">No failed builds."

        summary.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            }
        )
    return summary


def generate_team_summaries(teams_recent_builds: dict) -> dict:
    """
    Generate Slack message blocks for each team

    :param teams_recent_builds: a dict containing lists of failed and successful builds sorted by team
    :return: a dict of Slack message blocks sorted by team
    """
    logging.info("Generating team summaries...")
    team_summaries = {}

    for team in teams_recent_builds.keys():
        if len(teams_recent_builds[team]["Failed"]) == 0:
            continue

        summary_blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Build Error Notification Dispatch System"
                }
            },
            {
                "type": "divider"
            }
        ]
        successful_builds = len(teams_recent_builds[team]["Succeeded"])

        text = "*Successful Builds*\n"
        if successful_builds == 1:
            text += f">*{successful_builds} repository* had a successful build."
        else:
            text += f">*{successful_builds} repositories* had successful builds."

        summary_blocks.extend(
            [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": text
                    }
                },
                {
                    "type": "divider"
                }
            ]
        )

        text = "*Failed Builds*\n"
        if len(teams_recent_builds[team]["Failed"]) != 0:
            for build in teams_recent_builds[team]["Failed"]:
                text += ">• <" + build["RepositoryUrl"] + "|" + build["RepositorySlug"] + ">\n"
        else:
            text = ">No failed builds."

        summary_blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            }
        )

        team_summaries[team] = summary_blocks
    return team_summaries


def get_default_branch(repo_slug: str) -> str | None:
    """
    Get the name of a repository's default branch.

    :param repo_slug: the repository the default branch is being retrieved from
    :return: the name of a repositories default branch
    """
    url = f"https://api.bitbucket.org/2.0/repositories/{WORKSPACE}/{repo_slug}/refs/branches/"

    headers = {
        "Accept": "application/json"
    }

    auth = get_bitbucket_credentials()

    response = requests.request(
        "GET",
        url,
        auth=auth,
        headers=headers,
        params={
            "q": "name=\"main\" OR name=\"master\""
        }
    )

    try:
        if "error" in json.loads(response.text):
            logging.error("Failed to get default branch name: " + json.loads(response.text)["error"]["message"])
            return

        branches = json.loads(response.text)['values']
    except JSONDecodeError:
        logging.error("Failed to get default branch name: " + response.reason)
        return

    default_branch = branches[0]["name"]
    return default_branch


def get_recent_scheduled_pipeline(repo_slug: str, pipelines: list) -> dict | None:
    """
    Get the latest pipeline triggered by a schedule in the last week.

    :param repo_slug: the name of the repo containing the pipeline to be retrieved
    :param pipelines: a list of pipelines
    :return: the latest scheduled pipeline in a list
    """
    branch = get_default_branch(repo_slug)

    for pipeline in pipelines:
        # Convert created_on date value to usable datetime format
        creation_str = pipeline["created_on"].replace("T", " ").replace("Z", "")
        creation_date = datetime.strptime(creation_str, '%Y-%m-%d %H:%M:%S.%f')

        # Get today's date in UTC
        today_str = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
        today = datetime.strptime(today_str, '%Y-%m-%d %H:%M:%S.%f')

        recent = timedelta(weeks=1)

        # Get scheduled pipeline executed in the last week (if any)
        if today - creation_date <= recent:
            if pipeline["trigger"]["name"] == "SCHEDULE" and pipeline['target']['selector']['pattern'] == branch:
                logging.debug("This repo is in development.")
                return pipeline
        else:
            break
    return


def check_development_status(pipelines: list) -> bool:
    """
    Determine if a repository is currently in development

    :param pipelines: a page of the latest pipelines in the repo
    :return: a boolean determining if a repository is in development
    """
    logging.debug("Checking development status...")

    recent_pipelines = 0

    for pipeline in pipelines:
        # Convert created_on date value to usable datetime format
        creation_str = pipeline["created_on"].replace("T", " ").replace("Z", "")
        creation_date = datetime.strptime(creation_str, '%Y-%m-%d %H:%M:%S.%f')

        # Get today's date in UTC
        today_str = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
        today = datetime.strptime(today_str, '%Y-%m-%d %H:%M:%S.%f')

        recent = timedelta(weeks=1)

        # Check if pipeline was executed by user recently
        if today - creation_date <= recent:
            recent_pipelines += 1

            if pipeline["trigger"]["name"] != "SCHEDULE" or recent_pipelines > 1:
                logging.debug("This repo is in development.")
                return True
        else:
            break

    logging.debug("This repo is not in development")
    return False


def get_bitbucket_credentials() -> tuple:
    """
    Get Bitbucket credentials from environment

    :return: Bitbucket credentials
    """
    return os.getenv('BB_USER_ID'), os.getenv('BB_APP_PASS')


def get_latest_pipelines(repo_slug: str) -> list | None:
    """
    Get a page of the latest pipelines in a repository

    :param repo_slug: the name of the repo containing the pipelines to be retrieved
    :return: the latest pipelines
    """
    logging.debug(f"Retrieving latest pipelines for repo: {repo_slug}...")

    url = f"https://api.bitbucket.org/2.0/repositories/{WORKSPACE}/{repo_slug}/pipelines"

    headers = {
        "Accept": "application/json"
    }

    auth = get_bitbucket_credentials()

    response = requests.request(
        "GET",
        url,
        auth=auth,
        headers=headers,
        params={
            "sort": "-created_on"
        }
    )

    try:
        if "error" in json.loads(response.text):
            logging.error(f"Failed to get latest pipelines for {repo_slug}: " +
                          json.loads(response.text)["error"]["message"])
            return

        pipelines = json.loads(response.text).get('values')
    except JSONDecodeError:
        logging.error(f"Failed to get latest pipelines for {repo_slug}: " + response.reason)
        return

    return pipelines


def match_override(repo_slug: str, override: list | tuple) -> bool:
    """
    Search for a repository in the override list

    :param repo_slug: A repo slug to search for in the list of override patterns
    :param override: A list of patterns to ignore
    :return: a boolean dictating if a repo slug should be ignored
    """
    for pattern in override:
        pattern = re.compile(pattern)
        if pattern.search(repo_slug) is not None:
            return True

    return False


def get_active_services() -> dict:
    """
    Retrieve the repo names associated with the services listed in the Datadog service catalog

    :return: a dict of services sorted by team
    """
    logging.info("Retrieving active services...")

    teams = {}

    configuration = Configuration()
    with ApiClient(configuration) as api_client:
        api_instance = ServiceDefinitionApi(api_client)
        page = 0

        while True:
            response = api_instance.list_service_definitions(
                schema_version=ServiceDefinitionSchemaVersions.V2_1,
                page_number=page
            )

            if "errors" in response:
                logging.error(response["errors"][0])
                break

            for service in response['data']:
                # Extract repo name from Bitbucket repo URL in service definition
                schema = service['attributes']['schema']
                url_components = schema['links'][-1]['url'].split("/")
                team = schema['team']

                if team not in teams:
                    teams[team] = []

                if url_components[4] != "workspace":
                    teams[team].append({"RepositorySlug": url_components[4],
                                        "RepositoryUrl": schema['links'][-1]['url']})
            # Stop making requests when the response is empty
            if not response["data"]:
                break
            else:
                page += 1

    return teams


def process_services(teams: list[str], override: list[str], data: str, dry_run: bool) -> None:
    """
    Begin processing services

    :param teams: a list of teams to process the services of
    :param override: a list of repository names to ignore
    :param data: a filepath to pull service data from
    :param dry_run: a flag that causes script to not make changes
    """
    logging.info("Processing services...")

    if data:
        data_file = open(data)
        teams_services = json.load(data_file)
        data_file.close()
    else:
        teams_services = get_active_services()

    teams_recent_builds = {}

    for team in teams_services.keys():
        logging.info(f"Processing services for team: {team}...")

        if teams:
            if team not in teams:
                logging.info(f"Team {team} not in list. Skipping...")
                continue

        teams_recent_builds[team] = {"Succeeded": [], "Failed": []}
        for service in teams_services[team]:
            repo_slug = service['RepositorySlug']
            logging.debug(f"Processing service: {repo_slug}...")

            if override:
                if match_override(service, override):
                    logging.info(f"Bitbucket repo {repo_slug} overridden. Skipping...")
                    continue

            pipelines = get_latest_pipelines(repo_slug)

            if not pipelines:
                logging.info(f"No pipelines found in repo: {repo_slug}. Skipping...")
                continue

            in_development = check_development_status(pipelines)

            if not in_development:
                recent_scheduled_pipeline = get_recent_scheduled_pipeline(repo_slug, pipelines)

                if recent_scheduled_pipeline:
                    build_state = recent_scheduled_pipeline["state"].get("result")

                    if build_state:
                        build_state = build_state["name"]

                    if build_state == "FAILED":
                        teams_recent_builds[team]["Failed"].append(service)
                    else:
                        teams_recent_builds[team]["Succeeded"].append(service)
    logging.info("Services processed.")

    if dry_run:
        for team in teams_recent_builds.keys():
            logging.info(f"***Failed Builds for Team: {team}***")

            if len(teams_recent_builds[team]["Failed"]) == 0:
                continue

            for build in teams_recent_builds[team]["Failed"]:
                logging.info(build["RepositorySlug"])
    else:
        overall_summary = generate_overall_summary(teams_recent_builds)

        team_summaries = generate_team_summaries(teams_recent_builds)
        team_summaries[OVERALL_SUMMARY_RECIPIENT] = overall_summary

        post_team_summaries_to_slack(team_summaries)


def lambda_handler(event: dict, _) -> None:
    """
        A function that handles events received by a Lambda

        :param event: data to be processed
        :param _: lambda invocation, function, and runtime environment info
        """
    teams = event.get("teams")
    override = event.get("override")
    data = event.get("data")
    dry_run = event.get("dry_run", False)
    verbose = event.get("verbose", False)

    # Configure root logger level
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    process_services(teams, override, data, dry_run)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Bitbucket repository build state notification script")

    parser.add_argument(
        "-t", "--teams",
        help="A list of teams to process the services of. Processes services for all teams by default",
        dest="teams",
        nargs="+"
    )
    parser.add_argument(
        "-o", "--override",
        help="A list of repositories to ignore.",
        dest="override",
        nargs="+"
    )
    parser.add_argument(
        "-D", "--data",
        help="A filepath to pull service data from.",
        dest="data",
        default=None
    )
    parser.add_argument(
        "-d", "--dry_run",
        help="Run script in dry run mode, posting no messages to Slack.",
        dest="dry_run",
        action='store_true'
    )
    parser.add_argument(
        "-v", "--verbose",
        help="Run script in verbose mode, outputting more info in the logs.",
        dest="verbose",
        action='store_true'
    )

    args = parser.parse_args()
    lambda_handler(event={"teams": args.teams,
                          "override": args.override,
                          "data": args.data,
                          "dry_run": args.dry_run,
                          "verbose": args.verbose},
                   _=None)
