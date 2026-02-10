# =============================================================================
# LSD.law Wave Notifier — Configuration
# =============================================================================

# Schools your friend applied to.
# Use the EXACT names as they appear on https://lsd.law/recent-decisions
# (match the dropdown list on the site).
SCHOOLS = [
    "Harvard University",
    "Columbia University",
    "Stanford University",
    "Yale University",
    "University of Chicago",
    # Add or remove schools as needed
]

# ntfy.sh topic — your friend subscribes to this in the ntfy app.
# Make it unique and hard to guess so random people don't see notifications.
NTFY_TOPIC = "lsd-waves-a8f3x9"

# URL to scrape
CHECK_URL = "https://lsd.law/recent-decisions"

# Only notify about schools in the SCHOOLS list above.
# Set to False to get notified about ALL schools.
POLL_SCHOOLS_ONLY = True
