# Maintenance rules

When removing a feature, fully remove its implementation, endpoints, UI, unused
dependencies, and obsolete tests. Do not leave a disabled implementation behind.
Update current documentation to match; release history may retain historical notes.
Preserve existing user data unless its deletion is explicitly requested.

# UI consistency

Use antigravity/ui.css for shared controls on all app pages. Match the
Conversations New project (secondary) and New conversation (primary) styles;
retain the destructive color for deletion. Keep navigation between Conversations,
Files and Terminal available. Do not introduce a separate button theme per page.

# Publishing this repository

Run available local checks, publish authorized changes directly to main and bump
the app version for installable changes. GitHub Actions is off by default: do not
add, dispatch or depend on workflows unless the user explicitly enables them for
this project. Preserve branch protection and concurrent remote changes.
