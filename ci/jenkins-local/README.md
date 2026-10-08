# Run the Jenkinsfile on a local Jenkins

A throwaway Jenkins in Docker that builds this repo from its own `Jenkinsfile`. The agent runs as a
sibling container (`python:3.11-slim`) through the host's Docker socket, and the job checks out the
local clone, so no GitHub credential goes into the container.

```bash
docker build -t acc-jenkins ci/jenkins-local
docker run -d --name acc-jenkins -p 127.0.0.1:8099:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD:/repo:ro" -u root acc-jenkins

# once http://127.0.0.1:8099 answers: create the job and start a build (CSRF crumb first)
J=http://127.0.0.1:8099
CR=$(curl -s -c /tmp/jk "$J/crumbIssuer/api/json" | python -c "import sys,json;d=json.load(sys.stdin);print(d['crumbRequestField']+':'+d['crumb'])")
curl -s -b /tmp/jk -H "$CR" -H "Content-Type: application/xml" --data-binary @ci/jenkins-local/job.xml "$J/createItem?name=applied-ai-challenge"
curl -s -b /tmp/jk -H "$CR" -X POST "$J/job/applied-ai-challenge/build"
```

The setup wizard is off and the instance has no security realm: bind it to `127.0.0.1` only, as
above, and remove it after use (`docker rm -f acc-jenkins`). The job builds `main`; change the branch
in `job.xml` to build another one. `ALLOW_LOCAL_CHECKOUT` lets the git plugin clone from `/repo`.

Measured on 2026-10-09: `main` built green on all seven stages; a branch with one broken case failed
at `test` and skipped `canaries` and `audit`.
