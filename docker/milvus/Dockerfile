# The local Docker content store has truncated shared libraries used by curl in
# the upstream Milvus image.  Keep the official Milvus server unchanged and
# add a static BusyBox probe solely for its real HTTP health check.
FROM busybox:1.36.1-uclibc AS health_probe

FROM milvusdb/milvus:v2.6.25

COPY --from=health_probe /bin/busybox /busybox
