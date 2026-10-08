// The same gate as .github/workflows/ci.yml: every stage calls scripts/ci.sh, so the two
// pipelines run identical commands. Needs a Docker-capable agent (Docker Pipeline plugin).
pipeline {
  agent {
    docker {
      image 'python:3.11-slim'
      args '-u root'
    }
  }
  options {
    timeout(time: 20, unit: 'MINUTES')
    disableConcurrentBuilds(abortPrevious: true)
  }
  environment {
    UV_VERSION = '0.9.22'
    PATH = "/root/.local/bin:${env.PATH}"
  }
  stages {
    stage('setup')    { steps { sh 'apt-get update -qq && apt-get install -y -qq git >/dev/null && pip install -q "uv==${UV_VERSION}"' } }
    stage('install')  { steps { sh 'scripts/ci.sh install' } }
    stage('lint')     { steps { sh 'scripts/ci.sh lint' } }
    stage('types')    { steps { sh 'scripts/ci.sh types' } }
    stage('test')     { steps { sh 'scripts/ci.sh test' } }
    stage('canaries') { steps { sh 'scripts/ci.sh canaries' } }
    stage('audit')    { steps { sh 'scripts/ci.sh audit' } }
  }
}
