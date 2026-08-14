{
  # Keep this line accurate and one line long: `nix flake metadata` prints it,
  # and it is the first thing a cold agent learns about the repo.
  description = "streamer_shield -- Twitch scam-account detection: chat bot, dashboard, Postgres, and a Keras prediction API. Run `nix flake show` for the command map.";

  # nixpkgs is the only input, on purpose.
  #
  # flake-utils would buy exactly one thing here -- eachDefaultSystem -- which is
  # the three-line genAttrs below. In exchange it costs a second lock node in
  # every repo (flake-utils transitively pulls `systems`, so really two), a
  # second upstream that can break one repo and not the other forty, and a
  # hardcoded system list this repo cannot edit. That list is currently broken:
  # it still contains x86_64-darwin, which now throws (see `systems` below).
  #
  # nixos-unstable is the same channel the author's own NixOS config tracks, so
  # `nix develop` here and `nixos-rebuild` there resolve the same store paths and
  # share one cache.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    # `...` rather than a closed { self, nixpkgs }: adding a second input later
    # would otherwise fail with "called with unexpected argument 'self'".
    { nixpkgs, ... }:
    let
      lib = nixpkgs.lib;

      # x86_64-darwin is deliberately absent. nixpkgs 26.11 replaced that whole
      # attribute set with `throw "Nixpkgs 26.11 has dropped support for
      # x86_64-darwin"`. genAttrs is lazy, so plain `nix develop` on Linux would
      # not notice -- it detonates later, on `nix flake check --all-systems`.
      # Add it back only against a separate nixpkgs-26.05-darwin input.
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      # Stand-in for flake-utils.lib.eachDefaultSystem. Passes `pkgs` rather than
      # a system string, because that is what every call site below wants.
      forAllSystems = f: lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # ======================================================================
      # PER-REPO BLOCK 1 -- the toolchain
      # ======================================================================
      # Everything the commands below need. `nix flake check` realises this
      # closure, so a typo'd attr name fails at the flake gate instead of
      # surfacing as "command not found" halfway through a task.
      #
      # Explicit `pkgs.foo`, never `with pkgs; [ ... ]`: when an attr disappears
      # in a nixpkgs bump, `with` reports a bare undefined identifier with no
      # hint of which set it came from, and the name is not greppable.
      toolchain = pkgs: [
        # ---- this repo's ecosystem ----
        # 3.12 and NOT the newer python313, for two reasons that are properties
        # of this repo rather than taste: both Dockerfiles are FROM
        # python:3.12-slim, so the dev venv matches what ships; and
        # requirements-api.txt caps `tensorflow-cpu>=2.16,<2.20`, a range with no
        # cp313 wheels at all. On 3.12 an agent that actually needs the model can
        # `uv pip install -r requirements-api.txt` into the same venv -- on 3.13
        # that resolves to nothing installable. Do not "modernise" this pin
        # without lifting the TensorFlow cap first.
        pkgs.python312
        pkgs.uv
        pkgs.ruff

        # The bot and the dashboard talk to Postgres through asyncpg, and
        # tests/test_db_integration.py runs only when DB_HOST is set. asyncpg
        # needs no libpq, so this is here for the *server* side: initdb, pg_ctl
        # and psql let an agent bring up a throwaway cluster and exercise
        # `dev-run` and the skipped integration test without Docker.
        #
        # `.out` is load-bearing, not decoration. A bare `pkgs.postgresql_17` in
        # nativeBuildInputs (which is where both mkShell packages and the check
        # below land) also drags in the `dev` output -- and postgresql-17.10-dev
        # carries pg_config's clang + llvm, measured at 2337 MB of closure
        # against 146 MB for `out`. Nothing here compiles a PG extension, so drop
        # the headers. Do not "tidy" this back to a bare attr.
        pkgs.postgresql_17.out

        # ---- present in every repo in the fleet ----
        pkgs.git
        pkgs.jq
        pkgs.gnumake
      ];

      # ======================================================================
      # PER-REPO BLOCK 2 -- libraries that get dlopened, not linked
      # ======================================================================
      # manylinux wheels carry .so files that are dlopened at runtime, so neither
      # patchelf nor the nix linker ever sees them and NixOS has no /usr/lib for
      # them to find. stdenv.cc.cc.lib supplies libstdc++, which is the one that
      # breaks `import numpy` -- and numpy is a hard dependency of both
      # requirements-dev.txt and requirements-api.txt. zlib covers the wheels
      # that link it (h5py, and TensorFlow if someone installs it here). Keep
      # this list minimal -- LD_LIBRARY_PATH is a blunt instrument.
      nativeLibs = pkgs: [
        pkgs.stdenv.cc.cc.lib
        pkgs.zlib
      ];

      # ======================================================================
      # PER-REPO BLOCK 3 -- constant environment variables
      # ======================================================================
      # Only values that are constants belong here. Anything that must READ an
      # existing value (LD_LIBRARY_PATH), UNSET something (SOURCE_DATE_EPOCH) or
      # touch the work tree goes in the shellHook further down.
      #
      # This attrset is applied to BOTH surfaces -- the dev shell and every
      # `nix run` wrapper -- so a command cannot behave differently depending on
      # how it was invoked.
      #
      # Deliberately absent: every TWITCH_*/DB_*/FLASK_SECRET name from
      # .env.example. Those are per-developer secrets; config.py load_dotenv()s a
      # gitignored .env from the repo root, and baking a default here would put a
      # placeholder credential into the store and mask the missing-var error that
      # config.ConfigError exists to raise.
      envVars = pkgs: {
        # Keep uv on the nix interpreter. Left alone it downloads its own
        # portable CPython, which then resolves a different set of wheels than
        # this shell pins: two Pythons, one venv, no way to tell which is live.
        UV_PYTHON = "${pkgs.python312}/bin/python";
        UV_PYTHON_DOWNLOADS = "never";
        # /nix/store and the work tree are usually different filesystems, so
        # uv's default hardlink strategy warns on every single install.
        UV_LINK_MODE = "copy";
        PIP_DISABLE_PIP_VERSION_CHECK = "1";
      };

      # ======================================================================
      # PER-REPO BLOCK 4 -- the command map
      # ======================================================================
      # THE single source of truth. It generates `apps` (so `nix run .#test`
      # works), the `dev-*` wrappers on PATH inside the shell, and `dev-help`.
      # Nothing is written twice, so `nix flake show` can never disagree with
      # what `dev-test` actually runs.
      #
      # `build` is absent on purpose: this repo's artifacts are the two container
      # images from Dockerfile.bot / Dockerfile.api, built by
      # .github/workflows/build.yml against a docker daemon that no dev shell can
      # supply. A `dev-build` here would either wrap `docker build` and fail
      # wherever there is no socket, or lie. `nix flake show` reporting five
      # verbs instead of six is the honest answer.
      commands = pkgs: {
        setup = {
          # requirements-dev.txt pulls in requirements-bot.txt via `-r`, so this
          # one file is the whole local dependency set: twitchAPI, quart,
          # hypercorn, asyncpg, httpx, flask, numpy, pytest, pytest-asyncio.
          # TensorFlow is excluded by the repo's own decision (see the note at
          # the bottom of .envrc) -- the trainer and the prediction API run in
          # Docker. On this 3.12 pin `uv pip install -r requirements-api.txt`
          # into the same venv does work if you need them locally; it is a
          # ~600 MB download, which is why it is not part of setup.
          description = "(network) create .venv from requirements-dev.txt";
          text = ''
            uv venv "$REPO_ROOT/.venv"
            uv pip install --python "$REPO_ROOT/.venv/bin/python" -r "$REPO_ROOT/requirements-dev.txt"
          '';
        };
        test = {
          # The venv interpreter by absolute path, not a bare `pytest`. The
          # wrappers prepend the nix toolchain to PATH, so a bare name would
          # resolve to the store copy and miss every dependency `setup`
          # installed.
          #
          # pytest.ini sets asyncio_mode=auto and pythonpath=., so the modules at
          # the repo root import without an install step.
          # tests/test_db_integration.py self-skips unless DB_HOST is set; that
          # is a skip, not a pass, and running it needs a real Postgres.
          description = "run the pytest suite (needs `setup` first)";
          text = ''"$REPO_ROOT/.venv/bin/python" -m pytest "$@"'';
        };
        lint = {
          # This code has never been ruff-clean: a bare `dev-lint` currently
          # reports 77 findings, most of them import ordering. That is a true
          # statement about the repo, so it stays unconfigured -- do not silence
          # it with a generated pyproject.toml, and do not treat the count as a
          # regression you introduced.
          description = "ruff check";
          text = ''ruff check "$@"'';
        };
        fmt = {
          # There is no ruff/black config in this repo, so ruff's defaults apply
          # and the first unscoped run rewrites most files at once. Pass paths
          # (`dev-fmt db.py`) when you only mean to format what you touched.
          description = "ruff format (rewrites files; repo is not ruff-formatted yet)";
          text = ''ruff format "$@"'';
        };
        run = {
          # The bot process: hypercorn serves OAuth + /health on :5000 and the
          # EventSub webhook on :8080, and it needs TWITCH_*/DB_* from a
          # gitignored .env (copy .env.example) plus a reachable Postgres. Run by
          # absolute path so sys.path[0] is the repo root and `import config`
          # resolves from any cwd -- config.py's load_dotenv() then finds the
          # root .env too. The prediction API it calls over SHIELD_URL is the
          # other process (Dockerfile.api), not this one.
          description = "start the chat bot (needs .env + a reachable Postgres)";
          text = ''"$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/streamer_shield_chatbot.py" "$@"'';
        };
      };

      # ======================================================================
      # GENERIC MACHINERY -- byte-identical in all 41 repos, do not edit
      # ======================================================================

      # Prepend, never assign: a host LD_LIBRARY_PATH may be carrying something
      # the user needs, and clobbering it breaks binaries they launch from here.
      # Linux only -- on darwin the loader variable is DYLD_*, and exporting a
      # Linux-shaped value there is at best useless.
      ldPreamble =
        pkgs:
        lib.optionalString (pkgs.stdenv.hostPlatform.isLinux && nativeLibs pkgs != [ ]) ''
          export LD_LIBRARY_PATH="${lib.makeLibraryPath (nativeLibs pkgs)}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        '';

      # Every command gets $REPO_ROOT. `nix run` and `nix develop` both start in
      # whatever directory they were invoked from, so a bare `.venv` silently
      # forks a second environment as soon as an agent works from a subdirectory.
      # Note we do NOT cd there: commands act on the caller's cwd on purpose.
      rootPreamble = ''
        REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
        export REPO_ROOT
      '';

      # One derivation per command, reused by both `apps` and the dev shell, so
      # the two can never diverge. `dev-` prefixed because a bare `test` binary
      # earlier on PATH would shadow the POSIX shell builtin and quietly break
      # every script in the repo that uses it.
      wrappers =
        pkgs:
        lib.mapAttrs (
          name: cmd:
          pkgs.writeShellApplication {
            name = "dev-${name}";
            runtimeInputs = toolchain pkgs;
            runtimeEnv = envVars pkgs;
            meta.description = cmd.description;
            text = ''
              ${rootPreamble}
              ${ldPreamble pkgs}
              ${cmd.text}
            '';
          }
        ) (commands pkgs);

      helpFor =
        pkgs:
        let
          cmds = commands pkgs;
          names = lib.attrNames cmds;
          width = lib.foldl' (a: n: lib.max a (builtins.stringLength n)) 0 names;
          pad = n: n + lib.concatStrings (lib.genList (_: " ") (width - builtins.stringLength n));
          line = n: c: "  dev-${pad n}  ${c.description}";
        in
        pkgs.writeShellApplication {
          name = "dev-help";
          meta.description = "print this repo's command map (works offline)";
          text = ''
            cat <<'EOF'
            ${lib.concatStringsSep "\n" (lib.mapAttrsToList line cmds)}
            EOF
          '';
        };
    in
    {
      # `nix flake show` -- the discovery entrypoint, and deliberately the whole
      # machine-facing contract: every app carries a meta.description, which
      # `nix flake show` prints inline and `nix flake show --json` exposes at
      # .apps.<system>.<name>.description. Pure evaluation, so an agent gets the
      # entire command map in one cheap call without reading a README.
      #
      # Do NOT invent a top-level output for this (`agentManifest`, `probeThing`
      # ...). Nix answers with `warning: unknown flake output '<name>'` on every
      # single `nix flake check`, forever.
      apps = forAllSystems (
        pkgs:
        lib.mapAttrs (name: cmd: {
          type = "app";
          program = "${(wrappers pkgs).${name}}/bin/dev-${name}";
          meta.description = cmd.description;
        }) (commands pkgs)
      );

      # `nix develop` -- the toolchain, plus a dev-<verb> for every app.
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = toolchain pkgs ++ lib.attrValues (wrappers pkgs) ++ [ (helpFor pkgs) ];

          env = envVars pkgs;

          # Some C extensions and node-gyp addons compile at -O0, where glibc's
          # _FORTIFY_SOURCE becomes a hard error instead of a warning.
          hardeningDisable = [ "fortify" ];

          shellHook = ''
            # mkShell inherits SOURCE_DATE_EPOCH=315532800 (1980-01-01) from
            # stdenv, and any wheel or zip built in here then dies with "ZIP does
            # not support timestamps before 1980".
            unset SOURCE_DATE_EPOCH

            ${rootPreamble}
            ${ldPreamble pkgs}

            # Nothing networked, nothing stateful and nothing interactive above
            # this line, and nothing below it either. In particular this hook
            # does NOT do what .envrc does -- no venv creation, no `pip install`,
            # no `source .venv/bin/activate`, no dotenv load. Bootstrapping in
            # the hook makes a cold `nix develop -c pytest` start downloading
            # before it runs anything, on EVERY invocation -- the exact failure
            # an unattended agent cannot diagnose. That is what `dev-setup` is
            # for. direnv users keep using .envrc; it is untouched and the two
            # agree because both end up at "$REPO_ROOT/.venv".

            # The banner is interactive-only, and this guard is load-bearing:
            # shellHook output lands on the STDOUT of `nix develop -c <cmd>`, so
            # an unguarded echo corrupts anything parsing it
            # (`nix develop -c cat x.json | jq` fails to parse). $- is the only
            # reliable discriminator here -- it lacks `i` for `nix develop -c`
            # and has it at an interactive prompt. Do not test $PS1 (unset in
            # both) or $IN_NIX_SHELL (set in both). >&2 is the second layer, for
            # the case where a caller runs us on a pty.
            case $- in
              *i*) echo "streamer_shield dev shell -- 'dev-help' for the command map" >&2 ;;
            esac
          '';
        };
      });

      # `nix flake check` -- honest by construction. It realises the toolchain
      # closure (so a typo'd or currently-broken attr fails here) and builds
      # every wrapper, which runs shellcheck over every command text. Add real
      # test derivations beside it. NEVER add a check that always passes: an
      # agent reads "all checks passed!" as a signal, and a fake check makes
      # `nix flake check` a liar.
      #
      # The pytest suite is deliberately NOT wired in here: it imports quart,
      # twitchAPI and numpy from the pip-installed .venv, so a check that ran it
      # would need network inside the sandbox. `dev-test` is the gate for that.
      checks = forAllSystems (pkgs: {
        toolchain =
          pkgs.runCommand "toolchain-check"
            {
              nativeBuildInputs = toolchain pkgs ++ lib.attrValues (wrappers pkgs);
            }
            ''
              for verb in ${lib.escapeShellArgs (lib.attrNames (commands pkgs))}; do
                command -v "dev-$verb" > /dev/null || {
                  echo "dev-$verb is not on PATH" >&2
                  exit 1
                }
              done
              touch "$out"
            '';
      });

      # `nix fmt` -- formats the *Nix* in this repo; project code is `dev-fmt`.
      # nixfmt-tree (the treefmt wrapper) rather than bare nixfmt, because bare
      # nixfmt tries to parse every path handed to it and fails on non-Nix files.
      # This file ships already formatted, so `nix fmt` is a no-op rather than a
      # diff in 41 repos.
      formatter = forAllSystems (pkgs: pkgs.nixfmt-tree);
    };
}
