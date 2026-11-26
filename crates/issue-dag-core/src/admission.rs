//! The admission policy `taskalisk/threat-model` (admission rules AD1 to
//! AD10): whether an issue or a pull request is admitted, decided from the
//! run parameters and the observations alone.

use std::collections::{BTreeMap, BTreeSet};

use crate::forge::Forge;
use crate::observation::{Actor, Body, Missing, Observed, PullRequest, ReadScope, Repo};

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
    /// A lookup the rules reach was not recorded (bundle rule OB5).
    Missing(Missing),
}

impl From<Missing> for Undecided {
    fn from(missing: Missing) -> Self {
        Self::Missing(missing)
    }
}

fn value<T>(slot: Observed<T>) -> Result<T, Undecided> {
    match slot {
        Observed::Value(v) => Ok(v),
        Observed::Unavailable(why) => Err(Undecided::Unavailable(why)),
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
        let Some(actor) = actor else {
            return Ok(false);
        };
        let identity = Identity::of(actor);
        if self.allowlist.contains(&identity) {
            return Ok(true);
        }
        if identity.bot || !self.scope.contains(repo) {
            // A repository outside the scope is never judged (AD2).
            return Ok(false);
        }
        if self.read_codeowners && self.named_in_codeowners(repo, &identity.name)? {
            return Ok(true);
        }
        match association {
            Some("OWNER") => return Ok(true),
            Some("MEMBER" | "COLLABORATOR") | None => {}
            Some(_) => return Ok(false),
        }
        let login = actor.login.to_ascii_lowercase();
        let permission = value(self.forge.permission(repo, &login)?)?;
        Ok(matches!(
            permission.as_deref(),
            Some("admin" | "maintain" | "write")
        ))
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
        let mut seen: Vec<Option<Identity>> = vec![author.map(Identity::of)];
        let mut all = true;
        for editor in &body.editors {
            let identity = editor.as_ref().map(Identity::of);
            if seen.contains(&identity) {
                continue;
            }
            seen.push(identity);
            all &= self.trusted(editor.as_ref(), repo, None)?;
        }
        Ok(all)
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
        if pull.cross_repository != Some(false) {
            return Ok(false);
        }
        self.trusted(pull.author.as_ref(), home, None)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::{Identity, codeowners_persons};
    use crate::observation::Actor;

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
