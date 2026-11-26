//! Taskalisk: the adapters that turn a plan computed by `issue-dag-core`
//! into what the Taskalisk skill reads.
//!
//! [`render`] writes the JSON result lines of a plan. The command line that
//! runs a plan and writes them (flyingrobots/taskalisk#31) is not here yet.
//! The crate performs no I/O.

pub mod render;
