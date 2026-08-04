# Changelog

This file records user-visible changes for tagged releases.

## Unreleased

### Compatibility

- Bounded runtime dependencies to the verified 0.x API lines:
  `flow-res>=0.1.1,<0.2.0` and `injector>=0.24.0,<0.25.0`. This prevents a
  future minor release with breaking API changes from being selected by a
  PyPI installation while still allowing compatible patch releases.

## 0.2.0 - 2026-07-28

### Breaking changes

- Replaced the process-wide `Mediator` class API with mediator instances.
  `Mediator.initialize(...)` was removed; construct `Mediator(Injector(),
  registry)` instead.
- Removed handler auto-registration through
  `RequestHandler.__init_subclass__`. Applications now own a
  `HandlerRegistry` and register handlers explicitly.
- Duplicate registration no longer silently overwrites a mapping. It raises
  `DuplicateHandlerError`; use `replace()` for an intentional replacement of
  an existing mapping.
- Registration now rejects abstract handlers, non-handler classes, mismatched
  request types, unresolved generic contracts, and declared result types that
  conflict with the request contract.

### Added

- Added `HandlerRegistry` for isolated, application-owned handler mappings.
- Added `handler()`, `register()`, and `replace()` registration operations,
  with mediator convenience methods for explicit registration and replacement.
- Added public registration errors: `HandlerRegistrationError`,
  `InvalidHandlerError`, and `DuplicateHandlerError`.
- Added the `py.typed` marker and static typing regression coverage for package
  consumers.

## 0.1.1 - 2026-05-09

- Clarified comments in `RequestHandler`.

## 0.1.0 - 2026-04-13

- Initial release.
