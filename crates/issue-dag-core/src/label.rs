//! Labels of violations and warnings (format rule V12).

use core::fmt;

/// The label of a violation or a warning, as format rule V12 assigns it.
///
/// Every label is the label of a normative statement of the specification;
/// [`Label::as_str`] gives it as written there.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Label {
    /// C4: a line break the carrier does not allow.
    C4,
    /// C6: a line that is not an entry line.
    C6,
    /// C7: a duplicate key.
    C7,
    /// C8: a list value that does not end with `]`.
    C8,
    /// L1: a string that is not a reference.
    L1,
    /// L2: a resource key that is empty.
    L2,
    /// L3: an item that is not a meter claim.
    L3,
    /// L4: an integer out of bounds.
    L4,
    /// P3: a `.dag` that names another format version.
    P3,
    /// V1: an absent or malformed `.dag`.
    V1,
    /// V2: an unknown format key.
    V2,
    /// V3: an absent `.id`, or one that is not a string.
    V3,
    /// V4: an absent or wrong `.kind`.
    V4,
    /// V5: a task's keys.
    V5,
    /// V6: a container's keys.
    V6,
    /// V7: a self reference.
    V7,
    /// V8: an optional key.
    V8,
    /// V10: the advisory on `.size_hours` above 8. A warning, never a violation.
    V10,
    /// X1: a `.id` that is not the address of the issue (profile rule X1).
    X1,
}

impl Label {
    /// The label as the specification writes it, such as `"V5"`.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::C4 => "C4",
            Self::C6 => "C6",
            Self::C7 => "C7",
            Self::C8 => "C8",
            Self::L1 => "L1",
            Self::L2 => "L2",
            Self::L3 => "L3",
            Self::L4 => "L4",
            Self::P3 => "P3",
            Self::V1 => "V1",
            Self::V2 => "V2",
            Self::V3 => "V3",
            Self::V4 => "V4",
            Self::V5 => "V5",
            Self::V6 => "V6",
            Self::V7 => "V7",
            Self::V8 => "V8",
            Self::V10 => "V10",
            Self::X1 => "X1",
        }
    }
}

impl fmt::Display for Label {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::Label;

    const ALL: [Label; 19] = [
        Label::C4,
        Label::C6,
        Label::C7,
        Label::C8,
        Label::L1,
        Label::L2,
        Label::L3,
        Label::L4,
        Label::P3,
        Label::V1,
        Label::V2,
        Label::V3,
        Label::V4,
        Label::V5,
        Label::V6,
        Label::V7,
        Label::V8,
        Label::V10,
        Label::X1,
    ];

    /// A set of labels iterates in the ascending order corpus rule CC5 writes
    /// them in: the order of their text, so `V10` comes before `V2`.
    #[test]
    fn labels_order_as_their_text() {
        let mut by_ord = ALL;
        by_ord.sort_unstable();
        let mut by_text = ALL;
        by_text.sort_unstable_by_key(|l| l.as_str());
        assert_eq!(by_ord, by_text);
    }
}
