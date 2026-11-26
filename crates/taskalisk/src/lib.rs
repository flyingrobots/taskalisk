//! Taskalisk: the adapters that turn a plan computed by `issue-dag-core`
//! into what the Taskalisk skill reads, and the command line that plans a
//! live backlog.
//!
//! [`render`] writes the JSON result lines of a plan and performs no I/O;
//! [`views`] renders the ROADMAP block and the Mermaid flowcharts from the
//! same plan, also without I/O. [`cli`] is the `taskalisk` binary's `plan` command
//! (flyingrobots/taskalisk#31): it reads through the `gh` and `git` adapters,
//! plans with the core, and writes the rendered lines under the Parley
//! envelope ([`parley`]) with a receipt.

pub mod cli;
mod human;
pub mod parley;
pub mod render;
mod replay;
mod sha256;
pub mod views;
