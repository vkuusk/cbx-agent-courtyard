# Example team charters

A team charter is one directory of files that defines a team: who the agents
are, what each can and cannot be asked, and who may talk to whom. The format
is described in [docs/design/team-charter.md](../../docs/design/team-charter.md);
each subdirectory here is a complete, loadable example.

To try one: start the hub, open Admin, and under Teams add the example's
directory, then select it as the current team. The hub registers the agents
and creates the declared lines. Each agent still needs a project directory on
your machine; the expanded team view asks for it per agent and records the
answer in `workdirs.local.yml` beside the charter. That file is per machine
and must never be committed.

The files are the source of truth: edit them (or `git pull` a newer version)
and press "reload from disk" in the Teams view. The hub never watches the
filesystem.

- `aws-devops/`: three agents around one AWS estate. `infra-agent` owns the
  cloud, `tf-developer` writes the Terraform modules, `argocd-agent` owns
  GitOps delivery. Declares `discovery: manual`, so the two declared lines are
  the whole topology; tf-developer and argocd-agent deliberately have no line.
