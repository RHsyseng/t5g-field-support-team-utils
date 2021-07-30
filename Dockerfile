FROM registry.access.redhat.com/ubi8/python-38

WORKDIR /opt/
COPY k8s/build/sync.sh .

WORKDIR /app/bin/

COPY bin/* .
RUN pip3 install -r telco5g-jira-requirements.txt

# In order to build locally remove # and update sample.cfg file and uncommit this two steps:

#COPY cfg/sample.cfg .
#CMD [ "python3", "telco5g-jira.py", "sample.cfg"]
