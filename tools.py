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


def parse_jira_issues(json_data: List[Dict[str, Any]]) -> List[JiraIssue]:
    return [JiraIssue.model_validate(issue) for issue in json_data]


def prepare_message(issues):
    msg = ''
    for issue in issues:
        # Compose the message
        msg += f"[{issue.key}](https://jira.glowbyteconsulting.com/browse/{issue.key})\n"
        msg += f"Summary: {issue.fields.summary}\n"
        msg += f"Assignee: {issue.fields.assignee.displayName if issue.fields.assignee else 'Unassigned'}\n"
        msg += f"Status: {issue.fields.status.name}\n"
        if issue.fields.customfield_12671.completedCycles:
            msg += f"Time remaining: {issue.fields.customfield_12671.completedCycles[0].remainingTime.friendly}\n"
        else:
            msg += f"{issue.fields.customfield_12671.name}: NO SLA set for this issue\n"
        msg += f"\n\n"
    return msg


def etl(search_string: str = settings.jira.search_string, mode: str = 'broadcast') -> str:
    json_data = check_issues(jql_str=search_string)
    issues = parse_jira_issues(json_data)
    if mode == 'check':
        message = prepare_message(issues)
    else:
        issues_to_send = []
        for issue in issues:
            if (issue.fields.customfield_12671.completedCycles
                and issue.fields.customfield_12671.completedCycles[0].remainingTime.millis < 60 * 60 * 1000):
                    issues_to_send.append(issue)
        if issues_to_send:
            message = prepare_message(issues_to_send)
        else:
            message = f'No tracks to pay attention!'
    return message


if __name__ == '__main__':
    logger.debug(settings.jira.username, settings.jira.password)

    json_data = check_issues()
    issues = parse_jira_issues(json_data)

    for issue in issues:
        print(f"Issue: {issue.key} - {issue.fields.summary}")
        print(f"Assignee: {issue.fields.assignee.displayName if issue.fields.assignee else 'Unassigned'}")
        print(f"Status: {issue.fields.status.name}")
        if issue.fields.customfield_12671.completedCycles:
            print(f"Time remaining: {issue.fields.customfield_12671.completedCycles[0].remainingTime.friendly}")
        else:
            print(f"{issue.fields.customfield_12671.name}:NO SLA set for this issue")
        print("---")
