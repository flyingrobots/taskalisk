//! The Parley writer envelope (spec 0.2.1), ported from the vendored Python
//! writer `skills/taskalisk/scripts/parley_emit.py` for what `plan` needs.
//!
//! A [`Run`] owns everything the protocol asks of a program beside its
//! results: the bootstrap line, one sequence across stdout, stderr and the
//! receipt, the receipt under `.parley/receipts/<run>.jsonl` with its head,
//! steps, a copy of every result and error, the declared inputs and `inv`,
//! and `end`; the redaction of declared secrets; sidecars for receipt lines
//! over 65,536 bytes; retention by count; and `--human` prose. A usage
//! error never gets this far: [`startup_failed`] writes the one line a run
//! that cannot start writes.
//!
//! Every line is one compact JSON object with its keys in sorted order.
//!
//! Not ported: the state-directory fallback when `.parley` is not usable
//! (a receipt that cannot be created is a startup failure here), the
//! relocation when `.parley/.gitignore` is a user's file (it is created
//! when absent and otherwise left alone), the capture of stray output, the
//! redaction of a secret inside an object key, and `--dry-run`.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value, json};

use crate::sha256;

/// The text a declared secret's value is replaced with.
pub const REDACTED: &str = "[redacted]";
/// A receipt line longer than this many bytes is stored beside the receipt.
const SIDECAR_THRESHOLD: usize = 65_536;
/// An incomplete receipt older than this may be deleted by retention.
const INCOMPLETE_GRACE_MS: u128 = 24 * 60 * 60 * 1000;

/// The writer's own message types, by id and version.
pub mod schemas {
    /// `parley.run.bootstrap`
    pub const BOOTSTRAP: (&str, &str) = ("parley.run.bootstrap", "1.1.1");
    /// `parley.receipt.head`
    pub const HEAD: (&str, &str) = ("parley.receipt.head", "2.0.0");
    /// `parley.receipt.step`
    pub const STEP: (&str, &str) = ("parley.receipt.step", "1.0.0");
    /// `parley.receipt.inputs`
    pub const INPUTS: (&str, &str) = ("parley.receipt.inputs", "1.0.0");
    /// `parley.error`
    pub const ERROR: (&str, &str) = ("parley.error", "2.0.0");
    /// `parley.end`
    pub const END: (&str, &str) = ("parley.end", "1.0.0");
    /// `parley.startup.failed`
    pub const STARTUP_FAILED: (&str, &str) = ("parley.startup.failed", "1.0.0");
    /// `parley.sidecar`
    pub const SIDECAR: (&str, &str) = ("parley.sidecar", "1.0.0");
    /// `parley.redaction`
    pub const REDACTION: (&str, &str) = ("parley.redaction", "1.0.0");
    /// `parley.command`
    pub const COMMAND: (&str, &str) = ("parley.command", "1.0.0");
    /// `parley.schema`
    pub const SCHEMA: (&str, &str) = ("parley.schema", "1.0.0");
}

/// The `_schema` member of a line.
#[must_use]
pub fn schema_ref((id, version): (&str, &str)) -> Value {
    json!({"id": id, "version": version})
}

/// Milliseconds since the epoch.
#[must_use]
pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX))
}

const CROCKFORD: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/// A ULID: ten characters of millisecond time and sixteen of randomness,
/// Crockford base32, so run ids sort by creation time (spec 2.1).
#[must_use]
pub fn ulid(ms: u64) -> String {
    let mut head = [0_u8; 10];
    let mut t = ms;
    for slot in head.iter_mut().rev() {
        *slot = CROCKFORD[usize::try_from(t % 32).unwrap_or(0)];
        t /= 32;
    }
    let mut out: String = head.iter().map(|&b| char::from(b)).collect();
    out.extend(
        random_bytes()
            .iter()
            .map(|&b| char::from(CROCKFORD[usize::from(b & 31)])),
    );
    out
}

/// Sixteen bytes from the system's random source; when it cannot be read,
/// bytes derived from the clock and the process, which still differ per run.
fn random_bytes() -> [u8; 16] {
    let mut bytes = [0_u8; 16];
    let read = File::open("/dev/urandom").and_then(|mut f| {
        std::io::Read::read_exact(&mut f, &mut bytes)?;
        Ok(())
    });
    if read.is_err() {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let seed = format!("{nanos}:{}", std::process::id());
        let digest = sha256::hex(seed.as_bytes());
        for (slot, b) in bytes.iter_mut().zip(digest.bytes()) {
            *slot = b;
        }
    }
    bytes
}

/// The canonical JSON of a value: keys sorted, no whitespace, UTF-8.
#[must_use]
pub fn canonical(value: &Value) -> String {
    // serde_json's map is ordered by key, and it writes compact JSON.
    value.to_string()
}

/// `inv` (spec 2.2), the writer's derivation: SHA-256 over the canonical
/// JSON of `{tool, v, command, resolved, inputs: [{path, role?, sha256}]}`.
/// `None` when an input has no digest.
#[must_use]
pub fn inv(
    tool: &str,
    v: &str,
    command: &str,
    resolved: &Value,
    inputs: &[Value],
) -> Option<String> {
    let mut pre = Vec::new();
    for input in inputs {
        let mut d = Map::new();
        d.insert("path".into(), input.get("path")?.clone());
        if let Some(role) = input
            .get("role")
            .filter(|r| r.as_str().is_some_and(|r| !r.is_empty()))
        {
            d.insert("role".into(), role.clone());
        }
        d.insert("sha256".into(), input.get("sha256")?.clone());
        pre.push(Value::Object(d));
    }
    let text = canonical(&json!({
        "tool": tool, "v": v, "command": command, "resolved": resolved, "inputs": pre,
    }));
    Some(sha256::hex(text.as_bytes()))
}

/// Replaces each secret value in every string of `value`, and records the
/// JSON Pointer of each string it changed.
pub fn scrub(value: &mut Value, secrets: &[String], pointer: &str, found: &mut Vec<String>) {
    match value {
        Value::String(text) => {
            let mut changed = false;
            for secret in secrets {
                if text.contains(secret.as_str()) {
                    *text = text.replace(secret.as_str(), REDACTED);
                    changed = true;
                }
            }
            if changed {
                found.push(pointer.to_owned());
            }
        }
        Value::Array(items) => {
            for (i, item) in items.iter_mut().enumerate() {
                scrub(item, secrets, &format!("{pointer}/{i}"), found);
            }
        }
        Value::Object(map) => {
            for (key, item) in map.iter_mut() {
                let escaped = key.replace('~', "~0").replace('/', "~1");
                scrub(item, secrets, &format!("{pointer}/{escaped}"), found);
            }
        }
        _ => {}
    }
}

/// Where each copy of a record goes.
#[derive(Clone, Copy)]
struct To {
    stdout: bool,
    stderr: bool,
    receipt: bool,
}

/// Turns a line into prose for `--human`: `None` for the default rendering,
/// `Some("")` to print nothing.
pub type Human = fn(&Value) -> Option<String>;

/// What a run needs to start.
pub struct Start<'a> {
    /// The tool's name.
    pub tool: &'a str,
    /// The tool's version.
    pub v: &'a str,
    /// The command.
    pub command: &'a str,
    /// The working directory; the receipt goes under its `.parley`.
    pub cwd: &'a Path,
    /// The redacted argument vector.
    pub argv: Vec<String>,
    /// The resolved question and options.
    pub resolved: Value,
    /// The declared inputs (`path`, `role`), without digests.
    pub inputs: Vec<Value>,
    /// What the command reads, writes and touches (`effects`).
    pub effects: Value,
    /// The values of the declared secrets that are set.
    pub secrets: Vec<String>,
    /// The names of the declared secret variables that are set.
    pub secret_names: Vec<String>,
    /// The `--human` renderer, when asked for.
    pub human: Option<Human>,
    /// How many receipts of this tool to keep.
    pub retention: usize,
}

/// Why a run could not start: a `parley.startup.failed` line.
#[derive(Debug)]
pub struct StartupFailure {
    /// The `startup.` code.
    pub code: &'static str,
    /// What is wrong.
    pub problem: String,
    /// What to do.
    pub remedy: String,
}

/// Writes the one line of a run that cannot start, to stderr, and returns 3.
pub fn startup_failed(
    tool: &str,
    v: &str,
    failure: &StartupFailure,
    human: bool,
    secrets: &[String],
    stderr: &mut dyn Write,
) -> u8 {
    let mut problem = Value::String(failure.problem.clone());
    scrub(&mut problem, secrets, "", &mut Vec::new());
    let line = json!({
        "event": "startup.failed", "t": now_ms(), "seq": 0, "run": ulid(now_ms()),
        "tool": tool, "v": v, "code": failure.code, "problem": problem,
        "remedy": failure.remedy, "_schema": schema_ref(schemas::STARTUP_FAILED),
    });
    let text = if human {
        format!(
            "startup failed {}: {} ({})\n",
            failure.code,
            line["problem"].as_str().unwrap_or_default(),
            failure.remedy
        )
    } else {
        format!("{line}\n")
    };
    let _ = stderr.write_all(text.as_bytes());
    let _ = stderr.flush();
    3
}

/// One execution: a single sequence across stdout, stderr and the receipt;
/// the bootstrap line first, the head next, `end` last.
pub struct Run<'w> {
    tool: String,
    v: String,
    command: String,
    id: String,
    seq: u64,
    resolved: Value,
    inputs: Vec<Value>,
    stdout: &'w mut dyn Write,
    stderr: &'w mut dyn Write,
    receipt: File,
    receipt_path: PathBuf,
    receipt_dir: PathBuf,
    secrets: Vec<String>,
    human: Option<Human>,
    redacted_any: bool,
    error_reported: bool,
    sink_failed: bool,
    supplied: Option<Value>,
    bookkeeping: Value,
}

impl<'w> Run<'w> {
    /// Creates the receipt, writes the bootstrap line and the receipt head,
    /// and applies retention.
    ///
    /// # Errors
    ///
    /// A [`StartupFailure`] when no receipt can be created.
    pub fn start(
        start: Start<'_>,
        stdout: &'w mut dyn Write,
        stderr: &'w mut dyn Write,
    ) -> Result<Self, StartupFailure> {
        let parley = start.cwd.join(".parley");
        let receipt_dir = parley.join("receipts");
        let unwritable = |error: &std::io::Error| StartupFailure {
            code: "startup.receipt_unwritable",
            problem: format!(
                "no writable receipt location: {} is not usable ({error})",
                parley.display()
            ),
            remedy: "make .parley writable, or run from a writable directory".to_owned(),
        };
        // Every path a line names is under the receipt directory; one that
        // carries a declared secret cannot be printed (the Python writer
        // relocates first, and refuses only when every location carries it).
        let shown = receipt_dir.to_string_lossy();
        if start.secrets.iter().any(|s| shown.contains(s.as_str())) {
            return Err(StartupFailure {
                code: "startup.secret_in_path",
                problem: format!(
                    "the receipt path {shown} would carry a declared secret value, so no line can name it"
                ),
                remedy: "run from a directory whose path does not contain the secret".to_owned(),
            });
        }
        fs::create_dir_all(&parley).map_err(|e| unwritable(&e))?;
        if let Some(why) = hygiene(&parley).map_err(|e| unwritable(&e))? {
            return Err(StartupFailure {
                code: "startup.receipt_stageable",
                problem: format!("{why}; git add would stage a receipt"),
                remedy:
                    "make .parley/.gitignore the one line *, or remove it so the writer creates it"
                        .to_owned(),
            });
        }
        fs::create_dir_all(&receipt_dir).map_err(|e| unwritable(&e))?;
        let mut resolved = start.resolved;
        let mut resolved_found = Vec::new();
        scrub(&mut resolved, &start.secrets, "", &mut resolved_found);
        let mut id = ulid(now_ms());
        for _ in 0..16 {
            if !start.secrets.iter().any(|s| id.contains(s.as_str())) {
                break;
            }
            id = ulid(now_ms());
        }
        let receipt_path = receipt_dir.join(format!("{id}.jsonl"));
        let receipt = OpenOptions::new()
            .append(true)
            .create_new(true)
            .open(&receipt_path)
            .map_err(|e| unwritable(&e))?;
        let mut run = Self {
            tool: start.tool.to_owned(),
            v: start.v.to_owned(),
            command: start.command.to_owned(),
            id,
            seq: 0,
            resolved,
            inputs: start.inputs,
            stdout,
            stderr,
            receipt,
            receipt_path,
            receipt_dir,
            secrets: start.secrets,
            human: start.human,
            redacted_any: false,
            error_reported: false,
            sink_failed: false,
            supplied: None,
            bookkeeping: Value::Null,
        };
        run.bookkeeping = json!([
            {"op": "create", "scope": format!("{}/", run.receipt_dir.display())},
            {"op": "create", "scope": parley.join(".gitignore").display().to_string()},
            {"op": "delete", "scope": format!("{}/", run.receipt_dir.display())},
        ]);
        let inv = if run.inputs.is_empty() {
            inv(&run.tool, &run.v, &run.command, &run.resolved, &[])
        } else {
            None
        };
        run.bootstrap(inv.as_deref());
        run.head(
            inv.as_deref(),
            &start.argv,
            start.effects,
            &start.secret_names,
            &resolved_found,
        );
        run.retain(start.tool, start.retention);
        Ok(run)
    }

    /// The run id.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    /// The receipt's absolute path.
    #[must_use]
    pub fn receipt_path(&self) -> &Path {
        &self.receipt_path
    }

    /// The receipt head: the argument vector (secrets redacted), the
    /// resolved question, the declared inputs and the effects, with the
    /// bookkeeping.
    fn head(
        &mut self,
        inv: Option<&str>,
        argv: &[String],
        effects: Value,
        secret_names: &[String],
        resolved_found: &[String],
    ) {
        let mut effects = effects;
        effects["bookkeeping"] = self.bookkeeping.clone();
        let mut head = Map::new();
        head.insert("event".into(), json!("receipt.head"));
        head.insert("tool".into(), json!(self.tool));
        head.insert("v".into(), json!(self.v));
        if let Some(inv) = inv {
            head.insert("inv".into(), json!(inv));
        }
        let mut argv = json!(argv);
        let mut argv_found = Vec::new();
        scrub(&mut argv, &self.secrets, "", &mut argv_found);
        head.insert("argv".into(), argv);
        head.insert("resolved".into(), self.resolved.clone());
        let mut redacted = Map::new();
        if !argv_found.is_empty() {
            let indexes: Vec<u64> = argv_found
                .iter()
                .filter_map(|p| p.trim_start_matches('/').parse().ok())
                .collect();
            redacted.insert("argv".into(), json!(indexes));
        }
        if !resolved_found.is_empty() {
            // Pointers into the already-scrubbed `resolved`, as the Python
            // writer records them.
            redacted.insert("resolved".into(), json!(resolved_found));
        }
        if !secret_names.is_empty() {
            redacted.insert("env".into(), json!(secret_names));
        }
        if !redacted.is_empty() {
            self.redacted_any = true;
            head.insert("redacted".into(), Value::Object(redacted));
        }
        head.insert("inputs".into(), json!(self.inputs));
        head.insert("effects".into(), effects);
        self.emit(
            To {
                stdout: false,
                stderr: false,
                receipt: true,
            },
            Value::Object(head),
            schemas::HEAD,
            true,
        );
    }

    /// The bookkeeping the run may perform, declared ahead (spec 4.3).
    #[must_use]
    pub fn bookkeeping(&self) -> Value {
        self.bookkeeping.clone()
    }

    fn bootstrap(&mut self, inv: Option<&str>) {
        let mut line = Map::new();
        line.insert("event".into(), json!("run"));
        line.insert("tool".into(), json!(self.tool));
        line.insert("v".into(), json!(self.v));
        if let Some(inv) = inv {
            line.insert("inv".into(), json!(inv));
        }
        line.insert(
            "paths".into(),
            json!({"receipt": self.receipt_path.display().to_string()}),
        );
        self.emit(
            To {
                stdout: true,
                stderr: false,
                receipt: false,
            },
            Value::Object(line),
            schemas::BOOTSTRAP,
            false,
        );
    }

    /// A result: to stdout and the receipt. `line` carries `event` and
    /// `_schema`.
    pub fn result(&mut self, line: Value) {
        let schema = schema_of(&line);
        self.emit(
            To {
                stdout: true,
                stderr: false,
                receipt: true,
            },
            line,
            (&schema.0, &schema.1),
            false,
        );
    }

    /// A description (`parley.command`, `parley.schema`): to stdout and the
    /// receipt.
    pub fn describe(&mut self, line: Value, schema: (&str, &str)) {
        self.emit(
            To {
                stdout: true,
                stderr: false,
                receipt: true,
            },
            line,
            schema,
            false,
        );
    }

    /// One decision and why: the receipt only.
    pub fn step(&mut self, decision: &str, because: &str, detail: Option<Value>) {
        let mut line = Map::new();
        line.insert("event".into(), json!("receipt.step"));
        line.insert("decision".into(), json!(decision));
        line.insert("because".into(), json!(because));
        if let Some(detail) = detail {
            line.insert("detail".into(), detail);
        }
        self.emit(
            To {
                stdout: false,
                stderr: false,
                receipt: true,
            },
            Value::Object(line),
            schemas::STEP,
            false,
        );
    }

    /// A structured error (spec 6): to stderr and the receipt. The run then
    /// ends with status 2.
    pub fn error(
        &mut self,
        code: &str,
        problem: &str,
        remedy: Option<&str>,
        retryable: Option<bool>,
        detail: Option<Value>,
    ) {
        let mut line = Map::new();
        line.insert("event".into(), json!("error"));
        line.insert("code".into(), json!(code));
        line.insert("problem".into(), json!(problem));
        if let Some(remedy) = remedy {
            line.insert("remedy".into(), json!(remedy));
        }
        if let Some(retryable) = retryable {
            line.insert("retryable".into(), json!(retryable));
        }
        if let Some(detail) = detail {
            line.insert("detail".into(), detail);
        }
        self.emit(
            To {
                stdout: false,
                stderr: true,
                receipt: true,
            },
            Value::Object(line),
            schemas::ERROR,
            false,
        );
        self.error_reported = true;
    }

    /// Supplies the bytes of the declared input, whose digest the receipt
    /// carries and `inv` covers.
    pub fn input(&mut self, data: &str) {
        self.supplied = Some(json!(sha256::hex(data.as_bytes())));
    }

    fn finalise_inputs(&mut self) {
        if self.inputs.is_empty() {
            return;
        }
        let inputs: Vec<Value> = self
            .inputs
            .iter()
            .map(|decl| {
                let mut d = decl.clone();
                match &self.supplied {
                    Some(digest) => d["sha256"] = digest.clone(),
                    None => d["error"] = json!("input.unreadable"),
                }
                d
            })
            .collect();
        let mut line = Map::new();
        line.insert("event".into(), json!("receipt.inputs"));
        if let Some(inv) = inv(&self.tool, &self.v, &self.command, &self.resolved, &inputs) {
            line.insert("inv".into(), json!(inv));
        }
        line.insert("inputs".into(), json!(inputs));
        self.emit(
            To {
                stdout: false,
                stderr: false,
                receipt: true,
            },
            Value::Object(line),
            schemas::INPUTS,
            true,
        );
    }

    /// Closes the run and returns the exit status: 2 when an error was
    /// reported, 4 when a sink failed, else 0.
    #[must_use]
    pub fn end(mut self) -> u8 {
        self.finalise_inputs();
        let status: u8 = if self.sink_failed {
            4
        } else if self.error_reported {
            2
        } else {
            0
        };
        self.seq += 1;
        let line = json!({
            "event": "end", "t": now_ms(), "seq": self.seq, "run": self.id, "status": status,
            "receipt": self.receipt_path.display().to_string(), "redacted": self.redacted_any,
            "_schema": schema_ref(schemas::END),
        });
        let prose = match self.human {
            Some(_) if status == 0 => String::new(),
            Some(_) => format!(
                "end: status {status}{}; receipt at {}\n",
                if self.redacted_any {
                    ", receipt redacted"
                } else {
                    ""
                },
                self.receipt_path.display()
            ),
            None => format!("{line}\n"),
        };
        let out_ok = prose.is_empty() || write(self.stdout, &prose);
        let receipt_ok = write(&mut self.receipt, &format!("{line}\n"));
        if out_ok && receipt_ok { status } else { 4 }
    }

    /// Writes one record: the envelope added, every string scrubbed of the
    /// declared secrets, each copy to its sink.
    fn emit(&mut self, to: To, line: Value, schema: (&str, &str), writer: bool) {
        let Value::Object(mut fields) = line else {
            return;
        };
        fields.remove("_schema");
        let event = fields.remove("event").unwrap_or(Value::Null);
        let mut payload = Value::Object(fields);
        let mut found = Vec::new();
        if !writer {
            scrub(&mut payload, &self.secrets, "", &mut found);
        }
        let Value::Object(mut record) = payload else {
            return;
        };
        let seq = if event == json!("run") {
            0
        } else {
            self.seq + 1
        };
        self.seq = seq;
        record.insert("event".into(), event);
        record.insert("t".into(), json!(now_ms()));
        record.insert("seq".into(), json!(seq));
        record.insert("run".into(), json!(self.id));
        record.insert("_schema".into(), schema_ref(schema));
        let record = Value::Object(record);
        let text = format!("{record}\n");
        if to.stdout {
            let out = self.prose(&record).unwrap_or_else(|| text.clone());
            if !out.is_empty() && !write(self.stdout, &out) {
                self.sink_failed = true;
            }
        }
        if to.stderr {
            let out = self.prose(&record).unwrap_or_else(|| text.clone());
            if !out.is_empty() && !write(self.stderr, &out) {
                self.sink_failed = true;
            }
        }
        if to.receipt {
            if text.len() - 1 > SIDECAR_THRESHOLD && schema != schemas::HEAD {
                self.sidecar(seq, &text[..text.len() - 1]);
            } else if !write(&mut self.receipt, &text) {
                self.sink_failed = true;
            }
        }
        for pointer in found {
            self.redacted_any = true;
            self.seq += 1;
            let redaction = json!({
                "event": "redaction", "t": now_ms(), "seq": self.seq, "run": self.id,
                "in": seq, "at": pointer, "_schema": schema_ref(schemas::REDACTION),
            });
            if !write(&mut self.receipt, &format!("{redaction}\n")) {
                self.sink_failed = true;
            }
        }
    }

    /// `None` for JSON, else the prose of a line under `--human`.
    fn prose(&self, record: &Value) -> Option<String> {
        let human = self.human?;
        let text = human(record).unwrap_or_else(|| match record["event"].as_str() {
            Some("run") => String::new(),
            Some(event @ ("error" | "warning")) => {
                let remedy = record["remedy"]
                    .as_str()
                    .map_or_else(String::new, |r| format!(" ({r})"));
                format!(
                    "{event} {}: {}{remedy}",
                    record["code"].as_str().unwrap_or_default(),
                    record["problem"].as_str().unwrap_or_default()
                )
            }
            Some(event) => format!("{event}: {record}"),
            None => record.to_string(),
        });
        Some(if text.is_empty() || text.ends_with('\n') {
            text
        } else {
            text + "\n"
        })
    }

    /// Stores a long receipt line beside the receipt, and a `sidecar`
    /// record in its place.
    fn sidecar(&mut self, source: u64, text: &str) {
        let rel = format!("{}/{source}.json", self.id);
        let dir = self.receipt_dir.join(&self.id);
        let stored = fs::create_dir_all(&dir).and_then(|()| {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(self.receipt_dir.join(&rel))?;
            file.write_all(text.as_bytes())
        });
        if stored.is_err() {
            // The receipt keeps the record inline; the run ends with 4.
            self.sink_failed = true;
            let _ = write(&mut self.receipt, &format!("{text}\n"));
            return;
        }
        self.seq += 1;
        let line = json!({
            "event": "sidecar", "t": now_ms(), "seq": self.seq, "run": self.id,
            "source": source, "path": rel, "bytes": text.len(),
            "sha256": sha256::hex(text.as_bytes()), "_schema": schema_ref(schemas::SIDECAR),
        });
        if !write(&mut self.receipt, &format!("{line}\n")) {
            self.sink_failed = true;
        }
    }

    /// Past `count` receipts of this tool, deletes the oldest completed ones
    /// with their sidecars; other tools' receipts are never touched.
    fn retain(&mut self, tool: &str, count: usize) {
        let Ok(entries) = fs::read_dir(&self.receipt_dir) else {
            return;
        };
        let own = format!("{}.jsonl", self.id);
        let mut mine: Vec<(SystemTime, String)> = entries
            .filter_map(Result::ok)
            .filter_map(|entry| {
                let name = entry.file_name().into_string().ok()?;
                let path = entry.path();
                let head: Value = serde_json::from_str(first_line(&path)?.as_str()).ok()?;
                (path.extension().is_some_and(|x| x == "jsonl")
                    && head["event"] == "receipt.head"
                    && head["tool"] == tool)
                    .then_some(())?;
                Some((entry.metadata().ok()?.modified().ok()?, name))
            })
            .collect();
        let total = mine.len();
        if total <= count {
            return;
        }
        mine.retain(|(_, name)| *name != own);
        mine.sort();
        let now = SystemTime::now();
        let mut deleted = Vec::new();
        for (modified, name) in mine {
            if deleted.len() >= total - count {
                break;
            }
            let path = self.receipt_dir.join(&name);
            let old = now
                .duration_since(modified)
                .is_ok_and(|age| age.as_millis() > INCOMPLETE_GRACE_MS);
            if !(has_ended(&path) || old) || fs::remove_file(&path).is_err() {
                continue;
            }
            let _ = fs::remove_dir_all(self.receipt_dir.join(name.trim_end_matches(".jsonl")));
            deleted.push(name);
        }
        let decision = format!("retention: deleted {} receipt bundle(s)", deleted.len());
        let because = format!(
            "{total} receipts of {tool} exceeded its retention count of {count}; the oldest completed bundles of this tool are deleted with their sidecars, and no other tool's receipts are counted or touched (spec section 5.1)"
        );
        self.step(&decision, &because, Some(json!({"receipts": deleted})));
    }
}

/// The `(id, version)` a line names in `_schema`.
fn schema_of(line: &Value) -> (String, String) {
    let text = |key: &str| line["_schema"][key].as_str().unwrap_or_default().to_owned();
    (text("id"), text("version"))
}

fn write(sink: &mut dyn Write, text: &str) -> bool {
    sink.write_all(text.as_bytes())
        .and_then(|()| sink.flush())
        .is_ok()
}

/// `.parley/.gitignore` holding `*`, created when absent and never
/// overwritten (spec 5.2).
///
/// `Some(why)` when the file is a user's that would let git stage a
/// receipt: it has no line `*`, or it has a negation (`!`), which this
/// writer does not evaluate and so counts as one that can re-include
/// `receipts/`. The file is then left alone and the run refused, where the
/// Python writer relocates the receipt to the state directory.
fn hygiene(parley: &Path) -> std::io::Result<Option<String>> {
    let path = parley.join(".gitignore");
    match OpenOptions::new().write(true).create_new(true).open(&path) {
        Ok(mut file) => return file.write_all(b"*\n").map(|()| None),
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(e) => return Err(e),
    }
    let text = fs::read_to_string(&path)?;
    let lines: Vec<&str> = text.lines().map(|l| l.trim_end_matches('\r')).collect();
    Ok(if lines.contains(&"*") {
        lines.iter().find(|l| l.starts_with('!')).map(|negation| {
            format!(
                "{} has a negation, {negation}, that can re-include receipts/",
                path.display()
            )
        })
    } else {
        Some(format!(
            "{} exists without a line consisting of *",
            path.display()
        ))
    })
}

fn first_line(path: &Path) -> Option<String> {
    let text = fs::read_to_string(path).ok()?;
    text.lines().next().map(str::to_owned)
}

fn has_ended(path: &Path) -> bool {
    fs::read_to_string(path).is_ok_and(|text| {
        text.lines()
            .last()
            .and_then(|l| serde_json::from_str::<Value>(l).ok())
            .is_some_and(|l| l["event"] == "end")
    })
}

#[cfg(test)]
mod tests {
    use super::{canonical, choose_id, hygiene, inv, negation_reaches_receipts, scrub, ulid};
    use serde_json::json;

    /// The Python writer's `_negation_reaches_receipts`, case by case.
    #[test]
    fn a_negation_reaches_receipts_as_the_python_writer_decides() {
        for (line, reaches) in [
            ("*", false),
            ("plain", false),
            ("!.gitignore", false),
            ("!*.tmp", false),
            ("![!r]eceipts", false),
            ("!receipt", false),
            ("!receipts", true),
            ("!RECEIPTS", true),
            ("!rec*", true),
            ("!/receipts/", true),
            ("!**/receipts", true),
            ("!receipts   ", true),
            ("!r?ceipts", true),
            ("![q-s]eceipts", true),
            ("![]r]eceipts", true),
            ("!x/y", true),
            ("!a\\b", true),
            ("!r\teceipts", true),
            ("!réceipts", true),
            ("![receipts", true),
            ("![[:alpha:]]eceipts", true),
            ("foo\0bar", true),
        ] {
            assert_eq!(negation_reaches_receipts(line), reaches, "{line:?}");
        }
    }

    fn parley_dir(name: &str) -> std::path::PathBuf {
        let dir =
            std::env::temp_dir().join(format!("taskalisk-hygiene-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("a directory");
        dir
    }

    #[test]
    fn a_user_gitignore_is_judged_as_the_python_writer_judges_it() {
        for (text, refused) in [
            ("*\n!.gitignore\n", false),
            ("*\r\n", false),
            ("*\nfoo\0bar\n", true),
            ("*\n!receipts/\n", true),
            ("receipts/x\n", true),
        ] {
            let dir = parley_dir("judged");
            std::fs::write(dir.join(".gitignore"), text).expect("a .gitignore");
            let verdict = hygiene(&dir, "n").expect("read");
            assert_eq!(verdict.is_some(), refused, "{text:?}: {verdict:?}");
            let _ = std::fs::remove_dir_all(&dir);
        }
    }

    #[test]
    fn concurrent_first_runs_never_read_the_gitignore_empty() {
        for round in 0..20 {
            let dir = parley_dir(&format!("race-{round}"));
            let verdicts: Vec<_> = (0..8)
                .map(|n| {
                    let dir = dir.clone();
                    std::thread::spawn(move || hygiene(&dir, &format!("{round}-{n}")))
                })
                .collect::<Vec<_>>()
                .into_iter()
                .map(|t| t.join().expect("a thread"))
                .collect();
            for verdict in verdicts {
                assert_eq!(verdict.expect("read"), None, "round {round}");
            }
            assert_eq!(
                std::fs::read_to_string(dir.join(".gitignore")).expect("written"),
                "*\n"
            );
            let left: Vec<_> = std::fs::read_dir(&dir)
                .expect("the directory")
                .map(|e| e.expect("an entry").file_name())
                .collect();
            assert_eq!(
                left,
                vec![std::ffi::OsString::from(".gitignore")],
                "no temporary file left"
            );
            let _ = std::fs::remove_dir_all(&dir);
        }
    }

    #[test]
    fn a_run_id_that_always_carries_a_secret_refuses_the_run() {
        let secrets = ["SECRET".to_owned()];
        let mut tries = 0;
        let refused = choose_id(&secrets, || {
            tries += 1;
            "01SECRET0000000000000000000".to_owned()
        })
        .expect_err("no clean id");
        assert_eq!(refused.code, "startup.secret_in_path");
        assert_eq!(tries, 17, "the first id and 16 more tries");
        let mut ids = ["01SECRETX".to_owned(), "01CLEAN".to_owned()].into_iter();
        assert_eq!(
            choose_id(&secrets, || ids.next().expect("an id")).expect("a clean id"),
            "01CLEAN"
        );
    }

    #[test]
    fn a_ulid_is_26_crockford_characters_led_by_the_time() {
        let id = ulid(1_795_407_092_074);
        assert_eq!(id.len(), 26);
        // parley_emit.ulid(1795407092074)[:10]
        assert!(id.starts_with("01M839M6BA"), "{id}");
        assert!(id.bytes().all(|b| super::CROCKFORD.contains(&b)));
        assert_ne!(ulid(0), ulid(0), "the random part differs");
    }

    #[test]
    fn inv_is_the_python_writers_derivation() {
        // compute_inv("taskalisk", "2.0.0", "plan", {"a": 1}, [{"path": "p", "role": "r", "sha256": "d"}])
        // in skills/taskalisk/scripts/parley_emit.py.
        let resolved = json!({"a": 1});
        let inputs = [json!({"path": "p", "role": "r", "sha256": "d"})];
        assert_eq!(
            inv("taskalisk", "2.0.0", "plan", &resolved, &inputs).as_deref(),
            Some("e4b7405ef315fa28b71c1500643f25b9b0628c6a25ef437115a4fce8b5115856")
        );
        assert_eq!(inv("t", "1", "c", &resolved, &[json!({"path": "p"})]), None);
        assert_eq!(
            canonical(&json!({"b": [1, "é"], "a": null})),
            r#"{"a":null,"b":[1,"é"]}"#
        );
    }

    #[test]
    fn a_secret_is_replaced_and_its_pointer_kept() {
        let mut value = json!({"a/b": ["x tok y"], "c": "none"});
        let mut found = Vec::new();
        scrub(&mut value, &["tok".to_owned()], "", &mut found);
        assert_eq!(value, json!({"a/b": ["x [redacted] y"], "c": "none"}));
        assert_eq!(found, vec!["/a~1b/0".to_owned()]);
    }
}
