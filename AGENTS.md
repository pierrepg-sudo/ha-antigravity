# Maintenance rules

When removing a feature, fully remove its implementation, endpoints, UI, unused
dependencies, and obsolete tests. Do not leave a disabled implementation behind.
Update current documentation to match; release history may retain historical notes.
Preserve existing user data unless its deletion is explicitly requested.

# Publishing this repository

Run available local checks, publish authorized changes directly to main and bump
the app version for installable changes. GitHub Actions is off by default: do not
add, dispatch or depend on workflows unless the user explicitly enables them for
this project. Preserve branch protection and concurrent remote changes.
