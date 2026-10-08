# Run by `make populate` between DuckDB and mongoimport: passes the documents through unchanged
# and draws the progress of the whole run on stderr, redrawn every second.
# The Makefile sets: first and last (the batch), from and to (the run, all parquet rows included),
# start (the epoch the run started), batch and batches (the number of this batch, and of the run).

# the epoch, in any awk: srand() returns the previous seed, which srand() set to the time
function now() { srand(); return srand() }

function duration(s) {
    return s >= 3600 ? sprintf("%dh%02dm", s / 3600, s % 3600 / 60) : sprintf("%dm%02ds", s / 60, s % 60)
}

function thousands(n,   s, out) {
    s = sprintf("%d", n)
    while (length(s) > 3) {
        out = "," substr(s, length(s) - 2) out
        s = substr(s, 1, length(s) - 3)
    }
    return s out
}

# only the batches already done count: the rows DuckDB has read in this one are unknown
function draw(   done, total, width, filled, bar, i, eta) {
    done = first - from
    total = to - from + 1
    width = 30
    filled = int(done / total * width)
    for (i = 0; i < width; i++) bar = bar (i < filled ? "█" : "░")
    # the time per row of the batches done, for the rows left, minus what this batch has taken already
    eta = done ? (batch_start - start) / done * (total - done) - (now() - batch_start) : -1
    if (done && eta < 0) eta = 0
    printf "\r\033[K%s %3d%%  batch %d/%d  %s pictures  %s elapsed  ETA %s", \
        bar, done / total * 100, batch, batches, thousands(NR), duration(now() - start), \
        eta < 0 ? "?" : duration(eta) > "/dev/stderr"
}

BEGIN {
    batch_start = now()
    draw()
}

{ print }

NR % 1000 == 0 {
    t = now()
    if (t != drawn) {
        drawn = t
        draw()
    }
}

END {
    printf "\r\033[Kparquet rows %d-%d: %s pictures in %s\n", \
        first, last, thousands(NR), duration(now() - batch_start) > "/dev/stderr"
}
