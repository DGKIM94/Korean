function OUT = makeBalancedSubsetPools(opts)
% makeBalancedSubsetPools
%
% Purpose:
%   Select balanced k-location subset pools from a 3x3, 9-actuator array.
%
% Intended use:
%   Study 1 spatial uncertainty manipulation:
%       9 -> k
%       k -> 9
%   Use the same selected subsets for both directions.
%
% Example:
%   opts = struct();
%   opts.kList = [7 5 3];
%   opts.nSetsPerK = 9;
%   opts.seed = 7;
%   opts.baselineAcc = []; % optional 1x9 vector
%   OUT = makeBalancedSubsetPools(opts);
%
% Optional:
%   opts.baselineAcc = [0.92 0.88 0.91 0.90 0.86 0.89 0.93 0.87 0.92];
%   opts.confusion = 9x9 confusion matrix, optional

%% -------------------- defaults --------------------
if nargin < 1
    opts = struct();
end

opts = setDefault(opts, 'kList', [7 5 3]);
opts = setDefault(opts, 'nSetsPerK', 9);
opts = setDefault(opts, 'seed', 1);
opts = setDefault(opts, 'nStarts', 80);
opts = setDefault(opts, 'nIter', 6000);

% weights for optimization loss
opts = setDefault(opts, 'wInclusion', 100);
opts = setDefault(opts, 'wFeatureMean', 2);
opts = setDefault(opts, 'wExtreme', 0.5);

% 3x3 grid coordinates
% position numbering:
%   1 2 3
%   4 5 6
%   7 8 9
defaultXY = [
    1 1;
    2 1;
    3 1;
    1 2;
    2 2;
    3 2;
    1 3;
    2 3;
    3 3
];

opts = setDefault(opts, 'xy', defaultXY);
opts = setDefault(opts, 'baselineAcc', []);
opts = setDefault(opts, 'confusion', []);

rng(opts.seed);

nLoc = 9;
OUT = struct();
OUT.opts = opts;
OUT.pools = struct([]);

fprintf('\n=== Balanced subset pool generation ===\n');
fprintf('kList = [%s]\n', num2str(opts.kList));
fprintf('nSetsPerK = %d\n\n', opts.nSetsPerK);

%% -------------------- main loop --------------------
for kk = 1:numel(opts.kList)

    k = opts.kList(kk);

    candidates = nchoosek(1:nLoc, k);
    nCand = size(candidates, 1);

    candBin = false(nCand, nLoc);
    for i = 1:nCand
        candBin(i, candidates(i, :)) = true;
    end

    [features, featureNames] = computeSubsetFeatures( ...
        candidates, opts.xy, opts.baselineAcc, opts.confusion);

    [featuresZ, featMu, featSd] = zscoreManual(features);

    [bestIdx, diagInfo] = selectSubsetPoolAnneal( ...
        candBin, featuresZ, k, opts.nSetsPerK, opts);

    selectedSubsets = candidates(bestIdx, :);
    selectedBin = candBin(bestIdx, :);
    selectedFeatures = features(bestIdx, :);

    inclusionCounts = sum(selectedBin, 1);
    targetInclusion = opts.nSetsPerK * k / nLoc;

    OUT.pools(kk).k = k;
    OUT.pools(kk).allCandidates = candidates;
    OUT.pools(kk).selectedIdx = bestIdx;
    OUT.pools(kk).selectedSubsets = selectedSubsets;
    OUT.pools(kk).selectedBin = selectedBin;
    OUT.pools(kk).featureNames = featureNames;
    OUT.pools(kk).selectedFeatures = selectedFeatures;
    OUT.pools(kk).featureMean = mean(selectedFeatures, 1);
    OUT.pools(kk).featureStd = std(selectedFeatures, 0, 1);
    OUT.pools(kk).featureZMean = mean(featuresZ(bestIdx, :), 1);
    OUT.pools(kk).inclusionCounts = inclusionCounts;
    OUT.pools(kk).targetInclusion = targetInclusion;
    OUT.pools(kk).loss = diagInfo.bestLoss;
    OUT.pools(kk).diag = diagInfo;
    OUT.pools(kk).featureMuAllCandidates = featMu;
    OUT.pools(kk).featureSdAllCandidates = featSd;

    fprintf('--- k = %d ---\n', k);
    fprintf('Number of all possible subsets: %d\n', nCand);
    fprintf('Target inclusion count per actuator: %.2f\n', targetInclusion);
    fprintf('Actual inclusion counts:\n');
    disp(inclusionCounts);

    fprintf('Selected subsets:\n');
    disp(selectedSubsets);

    fprintf('Feature means of selected subsets:\n');
    for f = 1:numel(featureNames)
        fprintf('  %-18s %.4f\n', featureNames{f}, mean(selectedFeatures(:, f)));
    end
    fprintf('Best loss: %.6f\n\n', diagInfo.bestLoss);
end

fprintf('Done.\n');

end

%% ========================================================================
function [bestIdx, diagInfo] = selectSubsetPoolAnneal(candBin, featuresZ, k, nSets, opts)

nCand = size(candBin, 1);
nLoc = size(candBin, 2);

bestLoss = inf;
bestIdx = [];

for s = 1:opts.nStarts

    curIdx = randperm(nCand, nSets);
    curLoss = poolLoss(curIdx, candBin, featuresZ, k, nLoc, nSets, opts);

    temp0 = max(0.02, 0.1 * curLoss);

    for it = 1:opts.nIter

        newIdx = curIdx;

        replaceSlot = randi(nSets);

        available = true(1, nCand);
        available(curIdx) = false;
        availableIdx = find(available);

        newCandidate = availableIdx(randi(numel(availableIdx)));
        newIdx(replaceSlot) = newCandidate;

        newLoss = poolLoss(newIdx, candBin, featuresZ, k, nLoc, nSets, opts);

        temp = temp0 * (1 - it / opts.nIter) + 1e-6;

        accept = false;
        if newLoss < curLoss
            accept = true;
        else
            if rand < exp(-(newLoss - curLoss) / temp)
                accept = true;
            end
        end

        if accept
            curIdx = newIdx;
            curLoss = newLoss;
        end
    end

    if curLoss < bestLoss
        bestLoss = curLoss;
        bestIdx = curIdx;
    end
end

diagInfo.bestLoss = bestLoss;
diagInfo.nStarts = opts.nStarts;
diagInfo.nIter = opts.nIter;

end

%% ========================================================================
function L = poolLoss(idx, candBin, featuresZ, k, nLoc, nSets, opts)

selectedBin = candBin(idx, :);

% 1. Inclusion balance
inc = sum(selectedBin, 1);
target = nSets * k / nLoc;
incLoss = mean((inc - target).^2) / (target^2 + eps);

% 2. Selected pool should not be biased toward extreme feature values
selectedZ = featuresZ(idx, :);
featMeanLoss = mean(mean(selectedZ, 1).^2);

% 3. Penalize very extreme subset choices
extreme = max(0, abs(selectedZ) - 2);
extremeLoss = mean(extreme(:).^2);

L = opts.wInclusion * incLoss ...
  + opts.wFeatureMean * featMeanLoss ...
  + opts.wExtreme * extremeLoss;

end

%% ========================================================================
function [features, featureNames] = computeSubsetFeatures(candidates, xy, baselineAcc, confusion)

nCand = size(candidates, 1);

featureNames = {};
F = [];

% grid properties
minX = min(xy(:, 1));
maxX = max(xy(:, 1));
minY = min(xy(:, 2));
maxY = max(xy(:, 2));
gridCenter = mean(xy, 1);

for i = 1:nCand

    sub = candidates(i, :);
    coord = xy(sub, :);

    % pairwise distances
    d = [];
    for a = 1:size(coord, 1)
        for b = a+1:size(coord, 1)
            d(end+1) = norm(coord(a, :) - coord(b, :)); %#ok<AGROW>
        end
    end

    meanPairDist = mean(d);
    minPairDist = min(d);

    centroid = mean(coord, 1);
    centroidDistFromCenter = norm(centroid - gridCenter);

    distFromGridCenter = sqrt(sum((coord - gridCenter).^2, 2));
    meanDistFromCenter = mean(distFromGridCenter);

    nRows = numel(unique(coord(:, 2)));
    nCols = numel(unique(coord(:, 1)));

    isCorner = ...
        ((coord(:, 1) == minX | coord(:, 1) == maxX) & ...
         (coord(:, 2) == minY | coord(:, 2) == maxY));

    isBoundary = ...
        (coord(:, 1) == minX | coord(:, 1) == maxX | ...
         coord(:, 2) == minY | coord(:, 2) == maxY);

    nCorner = sum(isCorner);
    nEdge = sum(isBoundary & ~isCorner);
    nCenterLike = sum(~isBoundary);

    thisFeat = [
        meanPairDist, ...
        minPairDist, ...
        centroidDistFromCenter, ...
        meanDistFromCenter, ...
        nRows, ...
        nCols, ...
        nCorner, ...
        nEdge, ...
        nCenterLike
    ];

    thisNames = {
        'meanPairDist', ...
        'minPairDist', ...
        'centroidDist', ...
        'meanCenterDist', ...
        'nRows', ...
        'nCols', ...
        'nCorner', ...
        'nEdge', ...
        'nCenterLike'
    };

    % optional baseline accuracy
    if ~isempty(baselineAcc)
        accMean = mean(baselineAcc(sub));
        accStd = std(baselineAcc(sub));
        thisFeat = [thisFeat, accMean, accStd];
        thisNames = [thisNames, {'baselineAccMean', 'baselineAccStd'}];
    end

    % optional confusion score
    if ~isempty(confusion)
        pairConf = [];
        for a = 1:numel(sub)
            for b = a+1:numel(sub)
                p = sub(a);
                q = sub(b);
                pairConf(end+1) = 0.5 * (confusion(p, q) + confusion(q, p)); %#ok<AGROW>
            end
        end
        confMean = mean(pairConf);
        confMax = max(pairConf);
        thisFeat = [thisFeat, confMean, confMax];
        thisNames = [thisNames, {'confusionMean', 'confusionMax'}];
    end

    F(i, :) = thisFeat; %#ok<AGROW>

    if i == 1
        featureNames = thisNames;
    end
end

features = F;

end

%% ========================================================================
function [Z, mu, sd] = zscoreManual(X)

mu = mean(X, 1);
sd = std(X, 0, 1);
sd(sd == 0) = 1;

Z = (X - mu) ./ sd;

end

%% ========================================================================
function opts = setDefault(opts, fieldName, defaultValue)

if ~isfield(opts, fieldName) || isempty(opts.(fieldName))
    opts.(fieldName) = defaultValue;
end

end