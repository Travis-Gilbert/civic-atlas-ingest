//! civic-atlas-validate
//!
//! Validation CLI for the corpus tenant. Reads BuildingPresence and
//! ArtifactAnchor records from the Atlas backend's PostGIS via a
//! read-only DSN and checks them against the standard
//! ReconstructionSpec validators in our-civic-atlas-backend.
//!
//! Status: skeleton. The real validation logic depends on
//! ReconstructionSpec landing in our-civic-atlas-backend (Phase 2).
//! Once Codex finalizes that proto, this CLI imports the validators
//! from `civic-atlas-types` as a workspace path dependency.
//!
//! Usage:
//!   civic-atlas-validate corpus --city detroit
//!   civic-atlas-validate corpus --all
//!   civic-atlas-validate corpus --city detroit --report report.json

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};

#[derive(Parser, Debug)]
#[command(name = "civic-atlas-validate", version, about)]
struct Cli {
    #[command(subcommand)]
    command: Command,

    /// PostgreSQL DSN (read-only). Defaults to env CIVIC_ATLAS_CORPUS_DSN.
    #[arg(long, env = "CIVIC_ATLAS_CORPUS_DSN")]
    dsn: Option<String>,

    /// Enable verbose tracing.
    #[arg(long)]
    verbose: bool,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Validate corpus tenant records.
    Corpus {
        /// One-city run. Mutually exclusive with --all.
        #[arg(long)]
        city: Option<String>,

        /// All cities. Mutually exclusive with --city.
        #[arg(long)]
        all: bool,

        /// Optional JSON report output path.
        #[arg(long)]
        report: Option<String>,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    if cli.verbose {
        tracing_subscriber::fmt().with_env_filter("info,civic_atlas_validate=debug").init();
    } else {
        tracing_subscriber::fmt().with_env_filter("warn,civic_atlas_validate=info").init();
    }

    match cli.command {
        Command::Corpus { city, all, report } => {
            if city.is_some() && all {
                anyhow::bail!("--city and --all are mutually exclusive");
            }
            if city.is_none() && !all {
                anyhow::bail!("specify --city <slug> or --all");
            }

            let _dsn = cli
                .dsn
                .context("missing --dsn (set CIVIC_ATLAS_CORPUS_DSN)")?;

            // TODO(phase-5): connect to PostGIS, read corpus records,
            // run ReconstructionSpec validators per record, write report.
            // Blocked on Phase 2 ReconstructionSpec.

            let target = city.as_deref().unwrap_or("ALL");
            tracing::info!(target, "validate stub: nothing to validate yet");
            if let Some(path) = report {
                tracing::info!(%path, "report path noted; report writer not implemented");
            }
            anyhow::bail!(
                "civic-atlas-validate is a Phase 5 stub. The validator suite \
                 lands after our-civic-atlas-backend exposes ReconstructionSpec."
            );
        }
    }
}
