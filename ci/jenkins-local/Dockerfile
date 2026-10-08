FROM jenkins/jenkins:lts-jdk21
USER root
RUN apt-get update -qq && apt-get install -y -qq docker.io >/dev/null && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory '*'
USER jenkins
RUN jenkins-plugin-cli --plugins workflow-aggregator git docker-workflow
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false -Dhudson.plugins.git.GitSCM.ALLOW_LOCAL_CHECKOUT=true"
