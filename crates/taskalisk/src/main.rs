//! The `taskalisk` binary: see [`taskalisk::cli`].

use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<_> = std::env::args_os().collect();
    let (mut stdout, mut stderr) = (std::io::stdout().lock(), std::io::stderr().lock());
    let status = match std::env::current_dir() {
        Ok(cwd) => taskalisk::cli::main(&args, &cwd, &mut stdout, &mut stderr),
        Err(error) => taskalisk::parley::startup_failed(
            taskalisk::cli::TOOL,
            taskalisk::cli::VERSION,
            &taskalisk::parley::StartupFailure {
                code: "startup.cwd_unreadable",
                problem: format!("the working directory cannot be read: {error}"),
                remedy: "run from a directory that exists".to_owned(),
            },
            false,
            &[],
            &mut stderr,
        ),
    };
    ExitCode::from(status)
}
