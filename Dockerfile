FROM registry.fedoraproject.org/fedora:38
MAINTAINER "Telco5G Field Engineering Team"
RUN dnf -y install python3-pip gcc redhat-rpm-config python3-devel npm libxml2-devel xmlsec1-devel xmlsec1-openssl-devel libtool-ltdl-devel
COPY /src/ /srv/
WORKDIR /srv 
RUN pip3 install .
RUN npm ci --prefix t5gweb/static
EXPOSE 8080
