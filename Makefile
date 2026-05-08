IMAGE := iain247/calibre-mcp-server
VERSION := $(shell git describe --tags --abbrev=0 2>/dev/null || echo "latest")

.PHONY: build push release tag dev

build:
	docker build -t $(IMAGE):$(VERSION) -t $(IMAGE):latest .

push:
	docker push $(IMAGE):$(VERSION)
	docker push $(IMAGE):latest

release: build push

dev:
	docker build -t $(IMAGE):develop .
	docker push $(IMAGE):develop

tag:
	@read -p "Version (e.g. 1.0.0): " v; git tag $$v && echo "Tagged $$v"
