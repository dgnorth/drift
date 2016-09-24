import logging, getpass, os

log = logging.getLogger(__name__)

SLACKBOT_TOKEN = os.environ.get("DRIFT_SLACKBOT_KEY")

NOTIFICATION_CHANNEL = "#drift-notifications"


def post_message(message):
    if not SLACKBOT_TOKEN:
        print "No slackbot token. Cannot notify slack of '%s'" % message
        return

    final_message = "{}: {}".format(getpass.getuser(), message)
    try:
        from slacker import Slacker
    except ImportError:
        print "Message '{}' not posted to slack".format(message)
        print "Slack integration disabled. Enable slack with 'pip install slacker'"
    try:
        slack = Slacker(SLACKBOT_TOKEN)
        slack.chat.post_message(NOTIFICATION_CHANNEL, final_message)
    except Exception as e:
        log.warning("Cannot post '%s' to Slack: %s", final_message, e)
