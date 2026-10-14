use std::fmt;

#[derive(Debug, Clone)]
pub enum FsError {
    NotFound,
    Exists,
    NotDir,
    IsDir,
    NotEmpty,
    NoSpace,
    NoInodes,
    NameTooLong,
    Invalid(String),
    TooBig,
    Loop,
    TooManyLinks,
    TxTooLarge,
    Corrupt(String),
    Io(String),
}

impl FsError {
    /// Stable discriminant used to compare the real filesystem against the reference model.
    pub fn kind(&self) -> &'static str {
        match self {
            FsError::NotFound => "ENOENT",
            FsError::Exists => "EEXIST",
            FsError::NotDir => "ENOTDIR",
            FsError::IsDir => "EISDIR",
            FsError::NotEmpty => "ENOTEMPTY",
            FsError::NoSpace => "ENOSPC",
            FsError::NoInodes => "ENOINODES",
            FsError::NameTooLong => "ENAMETOOLONG",
            FsError::Invalid(_) => "EINVAL",
            FsError::TooBig => "EFBIG",
            FsError::Loop => "ELOOP",
            FsError::TooManyLinks => "EMLINK",
            FsError::TxTooLarge => "ETXTOOLARGE",
            FsError::Corrupt(_) => "ECORRUPT",
            FsError::Io(_) => "EIO",
        }
    }
}

impl fmt::Display for FsError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            FsError::NotFound => write!(f, "no such file or directory"),
            FsError::Exists => write!(f, "file exists"),
            FsError::NotDir => write!(f, "not a directory"),
            FsError::IsDir => write!(f, "is a directory"),
            FsError::NotEmpty => write!(f, "directory not empty"),
            FsError::NoSpace => write!(f, "no space left on device"),
            FsError::NoInodes => write!(f, "no free inodes"),
            FsError::NameTooLong => write!(f, "file name too long"),
            FsError::Invalid(s) => write!(f, "invalid argument: {s}"),
            FsError::TooBig => write!(f, "file too large"),
            FsError::Loop => write!(f, "too many levels of symbolic links"),
            FsError::TooManyLinks => write!(f, "too many links"),
            FsError::TxTooLarge => write!(f, "operation does not fit in one journal transaction"),
            FsError::Corrupt(s) => write!(f, "filesystem corrupt: {s}"),
            FsError::Io(s) => write!(f, "i/o error: {s}"),
        }
    }
}

impl std::error::Error for FsError {}

impl From<std::io::Error> for FsError {
    fn from(e: std::io::Error) -> FsError {
        FsError::Io(e.to_string())
    }
}

pub type Result<T> = std::result::Result<T, FsError>;
