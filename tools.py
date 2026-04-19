import html
import os
import sys
from datetime import datetime
from pprint import pprint

import json
import logging
from typing import Any, Dict, List, Tuple

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
                msg += f"NO SLA set for this track!\n"
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
            message = f'No tracks to pay attention!!!'
    return message


def get_my_issues(assignee: str = None) -> List[JiraIssue]:
    """Get issues assigned to the given user (defaults to configured jira username)."""
    if assignee is None:
        assignee = settings.jira.username
    jql = f'assignee = "{assignee}" AND status not in (Closed, Resolved) AND project != RTDMSUP ORDER BY updated DESC'
    data = check_issues(jql_str=jql)
    return parse_jira_issues(data)


def check_sla_warning(issue: JiraIssue, threshold_ms: int) -> bool:
    """Return True if the issue's TTFR SLA is ongoing and remaining time is below threshold."""
    try:
        cycle = issue.fields.customfield_12671.ongoingCycle
        if cycle and 0 < cycle.remainingTime.millis < threshold_ms:
            return True
    except Exception:
        pass
    return False


def format_my_issue_message(issue: JiraIssue, event: str, prev_status: str = None) -> str:
    """
    Format an HTML notification message for a personal track event.

    event values:
      'new'              — трек только что назначен
      'status_inprogress'— статус изменился на In Progress
      'status_changed'   — любое другое изменение статуса
      'sla_warning'      — SLA скоро истечёт
      'current'          — текущее состояние (для /mycheck)
    """
    jira_base = 'https://jira.glowbyteconsulting.com/browse'
    key = issue.key
    summary = html.escape(issue.fields.summary)
    status = html.escape(issue.fields.status.name)
    link = f'<a href="{jira_base}/{key}">{key}</a>'

    sla_part = ''
    for sla_field, sla_name in (
        (issue.fields.customfield_12671, 'TTFR'),
        (issue.fields.customfield_12670, 'SLA'),
    ):
        try:
            cycle = sla_field.ongoingCycle if sla_field else None
            if not cycle:
                continue
            remaining = html.escape(cycle.remainingTime.friendly)
            goal = html.escape(cycle.goalDuration.friendly)
            elapsed = html.escape(cycle.elapsedTime.friendly)
            if cycle.breached:
                line = f'\n{sla_name}: ❌ <b>просрочен на {remaining}</b> / цель {goal} (прошло {elapsed})'
            else:
                line = f'\n{sla_name}: ✅ осталось <b>{remaining}</b> / цель {goal} (прошло {elapsed})'
                if cycle.breachTime:
                    breach = html.escape(cycle.breachTime.friendly)
                    line += f' · дедлайн {breach}'
            sla_part += line
        except Exception:
            pass

    if event == 'new':
        header = f'📋 <b>Новый трек назначен:</b> {link}'
        body = f'{summary}\nСтатус: {status}'
    elif event == 'status_inprogress':
        header = f'✅ <b>Взят в работу:</b> {link}'
        prev = html.escape(prev_status) if prev_status else '?'
        body = f'{summary}\n{prev} → <b>{status}</b>'
    elif event == 'status_changed':
        header = f'🔄 <b>Статус изменился:</b> {link}'
        prev = html.escape(prev_status) if prev_status else '?'
        body = f'{summary}\n{prev} → <b>{status}</b>'
    elif event == 'sla_warning':
        header = f'⚠️ <b>SLA скоро истечёт:</b> {link}'
        body = f'{summary}\nСтатус: {status}'
    else:  # 'current'
        header = f'{link}'
        body = f'{summary}\nСтатус: {status}'

    return f'{header}\n{body}{sla_part}'


def check_personal_track_changes(
    current_issues: List[JiraIssue],
    previous_states: Dict[str, Dict],
    sla_warn_ms: int,
) -> Tuple[List[str], Dict[str, Dict]]:
    """
    Compare current issues against stored state.
    Returns (notifications, updated_state).
    If previous_states is None (first run) — returns no notifications, only initialised state.
    """
    is_first_run = previous_states is None
    prev = previous_states or {}
    notifications: List[str] = []
    new_states: Dict[str, Dict] = {}

    for issue in current_issues:
        key = issue.key
        current_status = issue.fields.status.name
        issue_prev = prev.get(key)

        if is_first_run or issue_prev is None:
            # Just initialise — no notifications on first sight
            sla_warned = False
        else:
            prev_status = issue_prev['status']
            sla_warned = issue_prev.get('sla_warned', False)

            # Status change
            if prev_status != current_status:
                if current_status.lower() == 'in progress':
                    event = 'status_inprogress'
                else:
                    event = 'status_changed'
                notifications.append(format_my_issue_message(issue, event, prev_status))

            # SLA warning (fire once per breach window)
            if check_sla_warning(issue, sla_warn_ms):
                if not sla_warned:
                    notifications.append(format_my_issue_message(issue, 'sla_warning'))
                    sla_warned = True
            else:
                sla_warned = False  # reset if SLA recovered or not applicable

        new_states[key] = {'status': current_status, 'sla_warned': sla_warned}

    return notifications, new_states


if __name__ == '__main__':
    # интересно посмотреть на расчет времени в выходные.
    logging.debug(f'username:{settings.jira.username}, password: {settings.jira.password}')
    # jql_string = 'key in (LTBEXT-3040)'
    # jql_string = 'status not in (Closed, Resolved) and (assignee = roman.nikulin)'
    # jql_string = '(("EXT System / Service" in ("Система Внутренних Списков", Anti-Fraud, Collection, "Collection CA", "Credit Scoring", "Data Verification", "Система принятия решений", "Автоматизированная cистема управления операционными рисками", "Система управления лимитами", "Система противодействия внутреннему мошенничеству", "Система противодействия мошенничеству", "Автоматизированная cистема управления операционными рисками", "Автоматизированная система управления операционными рисками") OR "EXT System / Service" in ("Anti Money Laundering") AND project in ("ROSBANK Support", "Почта Банк Support", "МТС Банк Support", "Банк Открытие Support") OR project in ("RTDM Support") AND labels = support) AND status not in (Closed, Resolved) AND (labels != nomon OR labels is EMPTY))'
    #jql_string = '(("EXT System / Service" in ("Система Внутренних Списков", Anti-Fraud, Collection, "Collection CA", "Credit Scoring", "Data Verification", "Система принятия решений", "Автоматизированная cистема управления операционными рисками", "Система управления лимитами", "Система противодействия внутреннему мошенничеству", "Система противодействия мошенничеству", "Автоматизированная cистема управления операционными рисками", "Автоматизированная система управления операционными рисками") OR "EXT System / Service" in ("Anti Money Laundering") AND project in ("ROSBANK Support", "Почта Банк Support", "OTP Bank Support", "МТС Банк Support", "Банк Открытие Support", "Ак Барс Support", "Банк СОЮЗ Support") OR project in ("RTDM Support") AND labels = support) AND status not in (Closed, Resolved) AND (labels != nomon OR labels is EMPTY))'
    jql_string = '(("EXT System / Service" in ("Система Внутренних Списков", Anti-Fraud, Collection, "Collection CA", "Credit Scoring", "Data Verification", "Система принятия решений", "Автоматизированная cистема управления операционными рисками", "Система управления лимитами", "Система противодействия внутреннему мошенничеству", "Система противодействия мошенничеству", "Автоматизированная cистема управления операционными рисками", "Автоматизированная система управления операционными рисками") OR "EXT System / Service" in ("Anti Money Laundering") AND project in ("ROSBANK Support", "Почта Банк Support", "OTP Bank Support", "МТС Банк Support", "Банк Открытие Support", "Ак Барс Support", "Банк СОЮЗ Support") OR project in ("RTDM Support") AND labels = support) AND status not in (Closed, Resolved) AND (labels != nomon OR labels is EMPTY)) and (status = "open" or assignee is EMPTY)'
    json_data = check_issues(jql_str=jql_string)
    # pprint(json_data, indent=4)
    issues = parse_jira_issues(json_data)
    import pandas as pd

    df = pd.DataFrame(issues)
    df.to_csv('data.csv', index=False, )
    print(len(issues))
    # message = prepare_message(issues)
    # message = etl(jql_string, mode='check')
    # print(message)
    # print('-'*100)
    # filename = datetime.strftime(datetime.now(), '%Y%m%d_%H%M%S')
    # with open(os.path.join(os.getcwd(), 'json', f'{filename}.json'), 'w') as ff:
    #     json.dump(obj=json_data, fp=ff, ensure_ascii=False, indent=4)

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
