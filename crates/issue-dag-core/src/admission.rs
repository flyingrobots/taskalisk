//! The admission policy `taskalisk/threat-model` (admission rules AD1 to
//! AD10): whether an issue or a pull request is admitted, decided from the
//! run parameters and the observations alone.

use std::collections::{BTreeMap, BTreeSet};

use crate::forge::Forge;
use crate::observation::{
    Actor, Body, Cause, Lookup, Missing, Observed, PullRequest, ReadScope, Repo,
};

/// An actor's identity (rule AD3): whether it is a bot, and its name in
/// ASCII lower case. A bot and a person never share an identity.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Identity {
    /// Whether the actor is a bot.
    pub bot: bool,
    /// The name, in ASCII lower case, without `app/` or `[bot]`.
    pub name: String,
}

impl Identity {
    /// The identity of an actor (rule AD3).
    #[must_use]
    pub fn of(actor: &Actor) -> Self {
        let mut identity = Self::of_entry(&actor.login);
        identity.bot |= actor.actor_type == "Bot";
        identity
    }

    /// The identity an allowlist entry names (rule AD4): an entry that ends
    /// in `[bot]` or begins with `app/` names the bot identity of the rest.
    #[must_use]
    pub fn of_entry(entry: &str) -> Self {
        let lower = entry.to_ascii_lowercase();
        let (app, name) = lower
            .strip_prefix("app/")
            .map_or((false, lower.as_str()), |rest| (true, rest));
        let (suffixed, name) = name
            .strip_suffix("[bot]")
            .map_or((false, name), |rest| (true, rest));
        Self {
            bot: app || suffixed,
            name: name.to_owned(),
        }
    }
}

/// Unicode line breaks of rule AD7.
const fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r' | '\u{0B}' | '\u{0C}' | '\u{1C}'
            ..='\u{1E}' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

/// Token separators of rule AD7: the Unicode `White_Space` characters and
/// U+001C to U+001F.
const fn is_separator(c: char) -> bool {
    matches!(
        c,
        '\u{09}'..='\u{0D}'
            | '\u{1C}'..='\u{1F}'
            | ' '
            | '\u{85}'
            | '\u{A0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200A}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
    )
}

/// The persons a CODEOWNERS text names (rule AD7), as logins in ASCII lower
/// case. Teams, bare `@`, and tokens that do not begin with `@` name nobody.
#[must_use]
pub fn codeowners_persons(text: &str) -> BTreeSet<String> {
    let mut persons = BTreeSet::new();
    for line in text.split(is_line_break) {
        let before_comment = line.split('#').next().unwrap_or_default();
        for token in before_comment
            .split(is_separator)
            .filter(|t| !t.is_empty())
            .skip(1)
        {
            let Some(name) = token.strip_prefix('@') else {
                continue;
            };
            if !name.is_empty() && !name.contains('/') {
                persons.insert(name.to_ascii_lowercase());
            }
        }
    }
    persons
}

/// Why a decision could not be made.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Undecided {
    /// A lookup the rules reach is unavailable (rule AD10): the run is
    /// incomplete.
    Unavailable(String),
    /// A reference resolves to no issue, and its unavailable slot records
    /// which part was not found (bundle rule OB17, profile rules D10 to
    /// D13): the run is incomplete, as for [`Undecided::Unavailable`], with
    /// the reason and the cause, which names the reference.
    NotFound(String, Cause),
    /// A lookup the rules reach was not recorded (bundle rule OB5).
    Missing(Missing),
}

impl From<Missing> for Undecided {
    fn from(missing: Missing) -> Self {
        Self::Missing(missing)
    }
}

/// The lookups that could not be made, gathered so that none hides another.
/// A caller notes each one and goes on reading whatever the rules still
/// reach. A missing slot (bundle rule OB5) takes precedence over an
/// unavailable one (AD10, profile rule F1). The one reported is the least
/// of its kind (bundle rule OB16): of missing slots, the least path from
/// `observations`; of unavailable ones, the least reason, and of those with
/// that reason the least cause (OB17), no cause first, and of those with
/// that cause the least reference ([`Cause`]). So the order of reading
/// never changes the result (profile rule D2).
#[derive(Debug, Default)]
pub struct Gaps {
    /// Each reason with its cause; `None` sorts before every cause.
    unavailable: BTreeSet<(String, Option<Cause>)>,
    missing: BTreeSet<Missing>,
}

impl Gaps {
    /// The value of `result`, or `None` after noting why it has none.
    pub fn note<T>(&mut self, result: Result<T, Undecided>) -> Option<T> {
        match result {
            Ok(v) => Some(v),
            Err(Undecided::Unavailable(why)) => {
                self.unavailable.insert((why, None));
                None
            }
            Err(Undecided::NotFound(why, cause)) => {
                self.unavailable.insert((why, Some(cause)));
                None
            }
            Err(Undecided::Missing(missing)) => {
                self.missing.insert(missing);
                None
            }
        }
    }

    /// Whether every lookup was made; otherwise the one to report.
    pub fn check(self) -> Result<(), Undecided> {
        if let Some(missing) = self.missing.into_iter().next() {
            return Err(Undecided::Missing(missing));
        }
        match self.unavailable.into_iter().next() {
            Some((why, None)) => Err(Undecided::Unavailable(why)),
            Some((why, Some(cause))) => Err(Undecided::NotFound(why, cause)),
            None => Ok(()),
        }
    }
}

/// The value of a lookup: the observation, when it was recorded and is
/// available.
pub fn lookup<T>(slot: Lookup<T>) -> Result<T, Undecided> {
    value(slot?)
}

fn value<T>(slot: Observed<T>) -> Result<T, Undecided> {
    match slot {
        Observed::Value(v) => Ok(v),
        Observed::Unavailable(why) => Err(Undecided::Unavailable(why)),
    }
}

/// Why an actor is not trusted in a repository (rule AD5): the step that
/// decided. Each variant holds what that step read, never issue text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Distrust {
    /// AD5 step 1: the actor is null, a deleted account.
    Deleted,
    /// AD2: the repository is outside the read scope, where nobody is
    /// trusted.
    OutOfScope,
    /// AD5 step 3: a bot that is not on the allowlist.
    Bot,
    /// AD5 step 6: an author association other than `OWNER`, `MEMBER` or
    /// `COLLABORATOR`, as recorded.
    Association(String),
    /// AD5 step 7: the permission on the repository is below `write`, as
    /// recorded, or `None`: not a collaborator.
    Permission(Option<String>),
}

impl Distrust {
    /// The rule that did not trust the actor: `AD2`, or `AD5.<step>`.
    #[must_use]
    pub const fn rule(&self) -> &'static str {
        match self {
            Self::Deleted => "AD5.1",
            Self::OutOfScope => "AD2",
            Self::Bot => "AD5.3",
            Self::Association(_) => "AD5.6",
            Self::Permission(_) => "AD5.7",
        }
    }
}

/// An actor that is not trusted, with why (rule AD5).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Distrusted {
    /// The actor's login as recorded; `None` for a deleted account.
    pub login: Option<String>,
    /// Why it is not trusted.
    pub why: Distrust,
}

impl Distrusted {
    fn of(actor: Option<&Actor>, why: Distrust) -> Self {
        Self {
            login: actor.map(|a| a.login.clone()),
            why,
        }
    }
}

/// Why an issue is not admitted (rule AD8).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NotAdmitted {
    /// Step 1: its author is not trusted. The body was not read.
    Author(Distrusted),
    /// Step 3: these editors of its body are not trusted, each once, in
    /// the order of the edit history. Never empty.
    Editors(Vec<Distrusted>),
}

/// Why a pull request that closes an issue is not admitted (rule AD9).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PullNotAdmitted {
    /// Its head is not a branch of the home repository: `cross_repository`
    /// is true or was not observed. Its author is not judged.
    NotSameRepository,
    /// Its author is not trusted in the home repository.
    Author(Distrusted),
}

impl PullNotAdmitted {
    /// The rule that did not admit it: `AD9` for its head, or its author's
    /// [`Distrust::rule`].
    #[must_use]
    pub const fn rule(&self) -> &'static str {
        match self {
            Self::NotSameRepository => "AD9",
            Self::Author(d) => d.why.rule(),
        }
    }
}

/// Admission decisions for one run.
pub struct Admission<'a, F: Forge + ?Sized> {
    forge: &'a F,
    scope: &'a ReadScope,
    allowlist: BTreeSet<Identity>,
    read_codeowners: bool,
    codeowners: BTreeMap<Repo, BTreeSet<String>>,
}

impl<'a, F: Forge + ?Sized> Admission<'a, F> {
    /// The policy for a run with this scope and these trust parameters.
    pub fn new(forge: &'a F, scope: &'a ReadScope, logins: &[String], codeowners: bool) -> Self {
        Self {
            forge,
            scope,
            allowlist: logins.iter().map(|l| Identity::of_entry(l)).collect(),
            read_codeowners: codeowners,
            codeowners: BTreeMap::new(),
        }
    }

    /// Rule AD5: whether `actor` is trusted in `repo`, with the author
    /// association when the actor is an issue's author.
    ///
    /// # Errors
    ///
    /// [`Undecided`] when a lookup the steps reach is unavailable or missing.
    pub fn trusted(
        &mut self,
        actor: Option<&Actor>,
        repo: &Repo,
        association: Option<&str>,
    ) -> Result<bool, Undecided> {
        Ok(self.distrust(actor, repo, association)?.is_none())
    }

    /// Rule AD5: why `actor` is not trusted in `repo`, or `None` when it is
    /// trusted. The association is the author's, when the actor is an
    /// issue's author. The reason is the step that decided (AD2 for a
    /// repository outside the scope), never a guess: a lookup that cannot be
    /// made is no reason (AD10).
    ///
    /// # Errors
    ///
    /// [`Undecided`] when a lookup the steps reach is unavailable or missing.
    pub fn distrust(
        &mut self,
        actor: Option<&Actor>,
        repo: &Repo,
        association: Option<&str>,
    ) -> Result<Option<Distrust>, Undecided> {
        let Some(actor) = actor else {
            return Ok(Some(Distrust::Deleted));
        };
        if !self.scope.contains(repo) {
            // A repository outside the scope is never judged (AD2), so not
            // even the allowlist trusts anyone there.
            return Ok(Some(Distrust::OutOfScope));
        }
        let identity = Identity::of(actor);
        if self.allowlist.contains(&identity) {
            return Ok(None);
        }
        if identity.bot {
            return Ok(Some(Distrust::Bot));
        }
        if self.read_codeowners && self.named_in_codeowners(repo, &identity.name)? {
            return Ok(None);
        }
        match association {
            Some("OWNER") => return Ok(None),
            Some("MEMBER" | "COLLABORATOR") | None => {}
            Some(other) => return Ok(Some(Distrust::Association(other.to_owned()))),
        }
        let login = actor.login.to_ascii_lowercase();
        let permission = value(self.forge.permission(repo, &login)?)?;
        if matches!(permission.as_deref(), Some("admin" | "maintain" | "write")) {
            return Ok(None);
        }
        Ok(Some(Distrust::Permission(permission)))
    }

    fn named_in_codeowners(&mut self, repo: &Repo, name: &str) -> Result<bool, Undecided> {
        if !self.codeowners.contains_key(repo) {
            let file = value(self.forge.codeowners(repo)?)?;
            let persons = file.map_or_else(BTreeSet::new, |f| codeowners_persons(&f.text));
            self.codeowners.insert(repo.clone(), persons);
        }
        Ok(self.codeowners.get(repo).is_some_and(|p| p.contains(name)))
    }

    /// Rule AD8, steps 2 and 3: whether every editor whose identity differs
    /// from the author's and from every editor before it is trusted. Every
    /// such editor is judged, even after one is not trusted.
    ///
    /// # Errors
    ///
    /// [`Undecided`] when a lookup is unavailable or missing.
    pub fn editors_trusted(
        &mut self,
        author: Option<&Actor>,
        body: &Body,
        repo: &Repo,
    ) -> Result<bool, Undecided> {
        Ok(self.untrusted_editors(author, body, repo)?.is_empty())
    }

    /// Rule AD8, steps 2 and 3: each editor whose identity differs from the
    /// author's and from every editor before it, and who is not trusted,
    /// with why, in the order of the edit history. Every such editor is
    /// judged, even after one is not trusted; the issue is admitted when the
    /// list is empty.
    ///
    /// # Errors
    ///
    /// [`Undecided`] when a lookup is unavailable or missing.
    pub fn untrusted_editors(
        &mut self,
        author: Option<&Actor>,
        body: &Body,
        repo: &Repo,
    ) -> Result<Vec<Distrusted>, Undecided> {
        let mut seen: BTreeSet<Option<Identity>> = BTreeSet::from([author.map(Identity::of)]);
        let mut untrusted = Vec::new();
        // Every editor is judged, even after one is undecided: a later
        // missing lookup must not hide behind an earlier unavailable one.
        let mut gaps = Gaps::default();
        for editor in &body.editors {
            if !seen.insert(editor.as_ref().map(Identity::of)) {
                continue;
            }
            if let Some(Some(why)) = gaps.note(self.distrust(editor.as_ref(), repo, None)) {
                untrusted.push(Distrusted::of(editor.as_ref(), why));
            }
        }
        gaps.check()?;
        Ok(untrusted)
    }

    /// Rule AD9: whether a pull request of the home repository `home` is
    /// admitted. The caller judges only one that closes an issue.
    ///
    /// # Errors
    ///
    /// [`Undecided`] when a lookup is unavailable or missing.
    pub fn pull_request_admitted(
        &mut self,
        pull: &PullRequest,
        home: &Repo,
    ) -> Result<bool, Undecided> {
        Ok(self.pull_request_not_admitted(pull, home)?.is_none())
    }

    /// Rule AD9: why a pull request of the home repository `home` is not
    /// admitted, or `None` when it is. The caller judges only one that
    /// closes an issue.
    ///
    /// # Errors
    ///
    /// [`Undecided`] when a lookup is unavailable or missing.
    pub fn pull_request_not_admitted(
        &mut self,
        pull: &PullRequest,
        home: &Repo,
    ) -> Result<Option<PullNotAdmitted>, Undecided> {
        if pull.cross_repository != Some(false) {
            return Ok(Some(PullNotAdmitted::NotSameRepository));
        }
        let author = pull.author.as_ref();
        Ok(self
            .distrust(author, home, None)?
            .map(|why| PullNotAdmitted::Author(Distrusted::of(author, why))))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use std::collections::BTreeMap;

    use super::{Admission, Gaps, Identity, Undecided, codeowners_persons};
    use crate::forge::{Observations, RecordedForge};
    use crate::observation::{Actor, Body, Missing, Observed, ReadScope, Repo};

    /// What `Gaps` reports after noting `gaps` in this order and then in
    /// the reverse order; the two must agree (OB16).
    fn reported(gaps: &[Undecided]) -> Result<(), Undecided> {
        let run = |order: &mut dyn Iterator<Item = &Undecided>| {
            let mut noted = Gaps::default();
            for gap in order {
                assert_eq!(noted.note::<()>(Err(gap.clone())), None);
            }
            noted.check()
        };
        let forward = run(&mut gaps.iter());
        assert_eq!(forward, run(&mut gaps.iter().rev()));
        forward
    }

    fn missing(path: &[&str], what: &str) -> Undecided {
        Undecided::Missing(Missing::at(path, what.to_owned()))
    }

    fn missing_path(result: Result<(), Undecided>) -> Vec<String> {
        match result {
            Err(Undecided::Missing(m)) => m.path,
            other => panic!("expected a missing slot, got {other:?}"),
        }
    }

    #[test]
    fn ob16_a_missing_slot_is_reported_before_an_unavailable_one() {
        let gaps = [
            Undecided::Unavailable("A".to_owned()),
            missing(
                &["permissions", "o/r", "zed"],
                "the permission of zed on o/r",
            ),
        ];
        assert_eq!(missing_path(reported(&gaps)), ["permissions", "o/r", "zed"]);
    }

    #[test]
    fn ob16_the_least_missing_path_is_reported() {
        // Member name by member name, each by its bytes: the home pull
        // requests before an issue, the repository of a permission before
        // its login, `o/r#10` before `o/r#2`, and a body by its issue's
        // reference. The words of the least sort last, so that ordering by
        // them, not by path, fails. The home listing against an issue is
        // tested only here: the listing is read only in a run without
        // roots, where it is the only source of seeds, so a run that lacks
        // it reads no issue and no corpus case can hold both.
        let cases: [(&[&str], &[&str]); 5] = [
            (&["home_open_issues"], &["issues", "o/r#2"]),
            (&["home_open_pull_requests"], &["issues", "o/r#2"]),
            (
                &["permissions", "o/r", "dave"],
                &["permissions", "o/s", "carol"],
            ),
            (&["issues", "o/r#10"], &["issues", "o/r#2"]),
            (&["issues", "o/r#2", "value", "body"], &["issues", "o/r#3"]),
        ];
        for (least, other) in cases {
            assert_eq!(
                missing_path(reported(&[missing(other, "a"), missing(least, "z")])),
                least
            );
        }
    }

    #[test]
    fn ob16_the_least_unavailable_reason_is_reported() {
        let gaps = [
            Undecided::Unavailable("timeout".to_owned()),
            Undecided::Unavailable("HTTP 502".to_owned()),
        ];
        assert_eq!(
            reported(&gaps),
            Err(Undecided::Unavailable("HTTP 502".to_owned()))
        );
    }

    #[test]
    fn ad2_an_allowlisted_actor_is_not_trusted_outside_the_scope() {
        let observations = Observations::default();
        let forge = RecordedForge::new(&observations);
        let scope = ReadScope {
            owners: BTreeSet::from(["o".to_owned()]),
            repositories: BTreeSet::new(),
        };
        let logins = ["dev".to_owned(), "helper[bot]".to_owned()];
        let mut admission = Admission::new(&forge, &scope, &logins, false);
        let home = Repo::parse("o/r").expect("repo");
        let other = Repo::parse("other/r").expect("repo");
        let dev = actor("dev", "User");
        assert_eq!(admission.trusted(Some(&dev), &other, None), Ok(false));
        assert_eq!(admission.trusted(Some(&dev), &home, None), Ok(true));
        // AD5 steps 2 and 3, in scope: an allowlisted bot is trusted and
        // another bot is not, with no lookup.
        let helper = actor("helper", "Bot");
        assert_eq!(admission.trusted(Some(&helper), &home, None), Ok(true));
        assert_eq!(admission.trusted(Some(&helper), &other, None), Ok(false));
        let stranger = actor("stranger", "Bot");
        assert_eq!(admission.trusted(Some(&stranger), &home, None), Ok(false));
    }

    #[test]
    fn ad8_a_missing_editor_lookup_is_not_hidden_by_an_earlier_unavailable_one() {
        // Every editor is judged (AD8 step 2): carol's permission is
        // unavailable, dave's was not recorded. The bundle is unusable (OB5).
        let home = Repo::parse("o/r").expect("repo");
        let mut observations = Observations::default();
        observations.permissions.insert(
            home.clone(),
            BTreeMap::from([(
                "carol".to_owned(),
                Observed::Unavailable("HTTP 502".to_owned()),
            )]),
        );
        let forge = RecordedForge::new(&observations);
        let scope = ReadScope {
            owners: BTreeSet::from(["o".to_owned()]),
            repositories: BTreeSet::new(),
        };
        let mut admission = Admission::new(&forge, &scope, &[], false);
        let body = Body {
            text: String::new(),
            editors: vec![Some(actor("carol", "User")), Some(actor("dave", "User"))],
        };
        let decided = admission.editors_trusted(Some(&actor("o", "User")), &body, &home);
        assert!(
            matches!(decided, Err(Undecided::Missing(_))),
            "got {decided:?}"
        );
    }

    fn actor(login: &str, actor_type: &str) -> Actor {
        Actor {
            login: login.to_owned(),
            actor_type: actor_type.to_owned(),
        }
    }

    #[test]
    fn bots_and_persons_never_share_an_identity() {
        let person = Identity::of(&actor("Dev", "User"));
        assert_eq!(person, Identity::of_entry("dev"));
        assert_ne!(person, Identity::of_entry("dev[bot]"));
        assert_eq!(
            Identity::of(&actor("dev", "Bot")),
            Identity::of_entry("dev[bot]")
        );
        assert_eq!(
            Identity::of(&actor("dev[bot]", "User")),
            Identity::of_entry("app/dev")
        );
    }

    #[test]
    fn codeowners_names_persons_after_the_path() {
        let text = "* @Alice @org/team @ a@example.com # @carol\r\ndocs/\u{a0}@bob\u{2028}@dave @erin\u{85}x @frank";
        let want: BTreeSet<String> = ["alice", "bob", "erin", "frank"]
            .into_iter()
            .map(str::to_owned)
            .collect();
        assert_eq!(codeowners_persons(text), want);
    }
}
