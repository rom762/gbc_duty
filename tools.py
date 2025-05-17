import os
import sys
from datetime import datetime
from pprint import pprint

import json
import logging
from typing import Any, Dict, List

from jira import JIRA

from models import JiraIssue

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

from config import settings

jira_options = {'server': settings.jira.url}
jira = JIRA(options=jira_options, basic_auth=(settings.jira.username, settings.jira.password))


def check_issues(jql_str: str = settings.jira.search_string) -> json:
    current_issues = jira.search_issues(jql_str=jql_str, json_result=True, )
    logging.debug(f'there are {current_issues["total"]} issues')
    return current_issues['issues']


def parse_jira_issues(data_json: List[Dict[str, Any]]) -> List[JiraIssue]:
    return [JiraIssue.model_validate(track) for track in data_json]


def prepare_message(tracks: List[JiraIssue]) -> str:
    msg = "No issues found"
    if len(tracks) > 0:
        msg = ''
        for track in tracks:
            # Compose the message
            msg += f"[{track.key}](https://jira.glowbyteconsulting.com/browse/{track.key})\n"
            msg += f"Summary: {track.fields.summary}\n"
            msg += f"Assignee: {track.fields.assignee.displayName if track.fields.assignee else 'Unassigned'}\n"
            msg += f"Status: {track.fields.status.name}\n"

            try:
                msg += f"Goal duration: {track.fields.customfield_12671.ongoingCycle.goalDuration.friendly}\n"
                msg += f"Elapsed Time: {track.fields.customfield_12671.ongoingCycle.elapsedTime.friendly}\n"
                msg += f"Time remaining: {track.fields.customfield_12671.ongoingCycle.remainingTime.friendly}\n"
            except Exception as e:
                msg += f"NO SLA set for this track\n"
            msg += f"\n\n"
    return msg


def etl(search_string: str = settings.jira.search_string, mode: str = 'broadcast') -> str:
    data_json = check_issues(jql_str=search_string)
    tracks = parse_jira_issues(data_json)
    logging.debug(f'Find {len(tracks)} tracks')
    if mode == 'check':
        message = prepare_message(tracks)
    else:
        issues_to_send = []
        for track in tracks:
            try:
                if (track.fields.customfield_12671.ongoingCycle
                    and track.fields.customfield_12671.ongoingCycle.remainingTime.millis <
                    track.fields.customfield_12671.ongoingCycle.goalDuration.millis
                    ):
                        issues_to_send.append(track)
            except Exception as e:
                logging.error(f'{e}')

        if issues_to_send:
            message = prepare_message(issues_to_send)
        else:
            message = f'No tracks to pay attention!'
    return message


if __name__ == '__main__':
    # интересно посмотреть на расчет времени в выходные.
    logging.debug(f'username:{settings.jira.username}, password: {settings.jira.password}')
    jql_string = 'key in (LTBEXT-3040)'
    # jql_string = 'status not in (Closed, Resolved) and (assignee = roman.nikulin)'
    # jql_string = '(("EXT System / Service" in ("Система Внутренних Списков", Anti-Fraud, Collection, "Collection CA", "Credit Scoring", "Data Verification", "Система принятия решений", "Автоматизированная cистема управления операционными рисками", "Система управления лимитами", "Система противодействия внутреннему мошенничеству", "Система противодействия мошенничеству", "Автоматизированная cистема управления операционными рисками", "Автоматизированная система управления операционными рисками") OR "EXT System / Service" in ("Anti Money Laundering") AND project in ("ROSBANK Support", "Почта Банк Support", "МТС Банк Support", "Банк Открытие Support") OR project in ("RTDM Support") AND labels = support) AND status not in (Closed, Resolved) AND (labels != nomon OR labels is EMPTY))'
    json_data = check_issues(jql_str=jql_string)
    pprint(json_data, indent=4)
    issues = parse_jira_issues(json_data)
    # print(len(issues))
    message = prepare_message(issues)
    print(message)
    print('-'*100)
    filename = datetime.strftime(datetime.now(), '%Y%m%d_%H%M%S')
    with open(os.path.join(os.getcwd(), 'json', f'{filename}.json'), 'w') as ff:
        json.dump(obj=json_data, fp=ff, ensure_ascii=False, indent=4)

    sys.exit()

    print('-'*200)
    for issue in issues:
        print(f"Issue: {issue.key} - {issue.fields.summary}")
        print(f"Assignee: {issue.fields.assignee.displayName if issue.fields.assignee else 'Unassigned'}")
        print(f"Status: {issue.fields.status.name}")

        print(f"{issue.fields.customfield_12671.name=}:")
        try:
            print(f"Time remaining friendly: {issue.fields.customfield_12671.ongoingCycle.remainingTime.friendly}")
            print(f"Time remaining: {issue.fields.customfield_12671.ongoingCycle.remainingTime.millis/1000/60} minutes")
        except IndexError as e:
            print(f"\tNO SLA set for this issue")

        print(f"{issue.fields.customfield_12670.name=}")
        try:
            print(f"OngoingCycle StartTime: {issue.fields.customfield_12670.ongoingCycle.startTime.friendly}")
            print(f"OngoingCycle GoalDuration: {issue.fields.customfield_12670.ongoingCycle.goalDuration.friendly}")
            print(f"OngoingCycle Remaining Time: {issue.fields.customfield_12670.ongoingCycle.remainingTime.friendly}")
            print(f"OngoingCycle Remaining Time millis: {issue.fields.customfield_12670.ongoingCycle.remainingTime.millis}")
        except AttributeError as e:
            print(f"No Sla to resolve")
        print("-"*100)
