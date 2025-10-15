import rdflib
import requests
import pyewts
import csv
from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD, Namespace, NamespaceManager
import boto3
import botocore
import gzip
import hashlib
import io
import json
import logging

LDSPDIBASEURL = "https://ldspdi.bdrc.io/"
EDITSERVBASEURL = "https://editserv.bdrc.io/"
CONVERTER = pyewts.pyewts()

SESSION = boto3.Session()
S3 = SESSION.client('s3')

BDR = Namespace("http://purl.bdrc.io/resource/")
BDR_uri = "http://purl.bdrc.io/resource/"
BDO = Namespace("http://purl.bdrc.io/ontology/core/")
BDA = Namespace("http://purl.bdrc.io/admindata/")
ADM = Namespace("http://purl.bdrc.io/ontology/admin/")

def fetch_op_commits(ldspdibaseurl="http://ldspdi.bdrc.io/"):
    """
    Fetches the list of all openpecha commits on BUDA
    """
    res = {}
    headers = {"Accept": "text/csv"}
    params = {"format": "csv"}
    with closing(
        requests.get(
            ldspdibaseurl + "/query/table/OP_allCommits",
            stream=True,
            headers=headers,
            params=params,
        )
    ) as r:
        reader = csv.reader(codecs.iterdecode(r.iter_lines(), "utf-8"))
        for row in reader:
            if not row[0].startswith("http://purl.bdrc.io/resource/IE0OP"):
                logging.error("cannot interpret csv line starting with " + row[0])
                continue
            res[row[0][34:]] = row[1]
    return res


def get_s3_folder_prefix(wlname, image_group_lname):
    """
    gives the s3 prefix (~folder) in which the volume will be present.
    inpire from https://github.com/buda-base/buda-iiif-presentation/blob/master/src/main/java/
    io/bdrc/iiif/presentation/ImageInfoListService.java#L73
    Example:
       - wlname=W22084, image_group_lname=I0886
       - result = "Works/60/W22084/images/W22084-0886/
    where:
       - 60 is the first two characters of the md5 of the string W22084
       - 0886 is:
          * the image group ID without the initial "I" if the image group ID is in the form I\\d\\d\\d\\d
          * or else the full image group ID (incuding the "I")
    """
    md5 = hashlib.md5(str.encode(wlname))
    two = md5.hexdigest()[:2]

    pre, rest = image_group_lname[0], image_group_lname[1:]
    if pre == 'I' and rest.isdigit() and len(rest) == 4:
        suffix = rest
    else:
        suffix = image_group_lname

    return 'Works/{two}/{RID}/images/{RID}-{suffix}/'.format(two=two, RID=wlname, suffix=suffix)

def gets3blob(s3Key):
    f = io.BytesIO()
    try:
        S3.download_fileobj('archive.tbrc.org', s3Key, f)
        return f
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == '404':
            return None
        else:
            raise

def get_image_list_s3(wlname, image_group_lname):
    s3key = get_s3_folder_prefix(wlname, image_group_lname)+"dimensions.json"
    blob = gets3blob(s3key)
    if blob is None:
        return None
    blob.seek(0)
    b = blob.read()
    ub = gzip.decompress(b)
    s = ub.decode('utf8')
    data = json.loads(s)
    return data

def get_image_list_iiifpres(wlname, image_group_lname):
    r = requests.get(f"http://iiifpres.bdrc.io/il/v:bdr:{vol_name}")
    return r.json()

def get_image_list(wlname, image_group_lname, source="s3", reorder_with_bvm=False):
    il = None
    if source == "s3":
        il = get_image_list_s3(wlname, image_group_lname)
    else:
        il = get_image_list_iiifpres(wlname, image_group_lname)
    return il

def scans_res_from_model(g, wlname):
    res = {
        "source_metadata": {
            "id": "http://purl.bdrc.io/resource/"+wlname
        },
        "image_groups": {}
    }
    wres = BDR[wlname]
    try:
        adm = g.value(predicate=ADM.adminAbout, object=wres)
        res["source_metadata"]["status"] = str(g.value(adm, ADM.status))
        res["source_metadata"]["access"] = str(g.value(adm, ADM.access))
        if (adm, ADM.restrictedInChina, Literal(True)) in g:
            res["source_metadata"]["geo_restriction"] = ["CN"]
        o = g.value(predicate=BDO.outlineOf, object=wres)
        if o:
            res["source_metadata"]["outline"] = str(o)
        mwres = g.value(wres, BDO.instanceReproductionOf)
        res["source_metadata"]["reproduction_of"] = str(mwres)
        for _, _, cs in g.triples((mwres, BDO.copyright, None)):
            res["source_metadata"]["copyright_status"] = str(cs)
        if "copyright_status" not in res["source_metadata"]:
            res["source_metadata"]["copyright_status"] = "http://purl.bdrc.io/resource/CopyrightPublicDomain"
        res["source_metadata"]["reproduction_of"] = str(mwres)
        for _, _, l in g.triples((mwres, SKOS.prefLabel, None)):
            if l.language == "bo-x-ewts":
                res["source_metadata"]["title"] = CONVERTER.toUnicode(l.value)
                break
            else:
                res["source_metadata"]["title"] = l.value
        res["source_metadata"]["languages"] = set()
        for _, _, wa in g.triples((mwres, BDO.instanceOf, None)):
            for _, _, l in g.triples((wa, BDO.language, None)):
                for _, _, lt in g.triples((l, BDO.langBCP47Lang, None)):
                    res["source_metadata"]["languages"].add(lt.value)
            for _, _, aac in g.triples((wa, BDO.creator, None)):
                if (aac, BDO.role, BDR.R0ER0009) or (aac, BDO.role, BDR.R0ER0009) in g:
                    for _, _, p in g.triples((aac, BDO.agent, None)):
                        for _, _, l in g.triples((p, SKOS.prefLabel, None)):
                            if l.language == "bo-x-ewts":
                                res["source_metadata"]["author"] = CONVERTER.toUnicode(l.value)
                                break
                            else:
                                res["source_metadata"]["author"] = l.value
        res["source_metadata"]["languages"] = list(res["source_metadata"]["languages"])
        for _, _, ig in g.triples((wres, BDO.instanceHasVolume, None)):
            if g.value(ig, BDO.volumeNumber) is None or g.value(ig, BDO.volumePagesTotal) is None:
                continue
            iglname = str(ig)[str(ig).rfind('/')+1:]
            res["image_groups"][iglname] = {}
            iginfo = res["image_groups"][iglname]
            iginfo["id"] = str(ig)
            iginfo["total_pages"] = int(g.value(ig, BDO.volumePagesTotal))
            iginfo["volume_number"] = int(g.value(ig, BDO.volumeNumber))
            iginfo["volume_pages_bdrc_intro"] = int(g.value(ig, BDO.volumePagesTbrcIntro, default=Literal(0)))
            for _, _, l in g.triples((ig, SKOS.prefLabel, None)):
                if l.language == "bo-x-ewts":
                    iginfo["title"] = CONVERTER.toUnicode(l.value)
                    break
                else:
                    iginfo["title"] = l.value
    finally:
        return res

def to_lname(uriname):
    uriname = str(uriname)
    if "/" not in uriname:
        return uriname
    return uriname[uriname.rfind('/')+1:]

def ao_res_from_model(g, rlname):
    res = {
        "mw_lname": None,
        "mw_outline_lname": None,
        "mw_root_lname": None,
        "in_collection": [],
        "volname_to_volnum": {}
    }
    rres = BDR[rlname]
    try:
        mwres = g.value(rres, BDO.instanceReproductionOf)
        #print(g.serialize(format="ttl"))
        mwres_lname = to_lname(mwres)
        res["mw_lname"] = mwres_lname
        res["mw_root_lname"] = mwres_lname
        for _, _, c in g.triples((None, BDO.inCollection, None)):
            c_lname = to_lname(c)
            res["in_collection"].append(c_lname)
        for o, _, _ in g.triples((None, BDO.outlineOf, None)):
            res["mw_outline_lname"] = to_lname(o)
        for _, _, v in g.triples((rres, BDO.instanceHasVolume, None)):
            if g.value(v, BDO.volumeNumber) is None:
                continue
            vlname = to_lname(v)
            vnum = int(g.value(v, BDO.volumeNumber))
            res["volname_to_volnum"][vlname] = vnum
    finally:
        return res

def get_buda_scan_info(wlname):
    headers = {"Accept": "text/turtle"}
    params = {"R_RES": "bdr:"+wlname}
    res = None
    g = rdflib.Graph()
    try:
        req = requests.get(
            LDSPDIBASEURL + "query/graph/OP_info",
            headers=headers,
            params=params,
        )
        g.parse(data=req.text, format="ttl")
        res = scans_res_from_model(g, wlname)
    except Exception as e:
        logging.error("get_buda_scan_info failed for "+wlname+": "+str(e))
    finally:
        return res

def get_buda_AO_info(rlname):
    headers = {"Accept": "text/turtle"}
    params = {"R_RES": "bdr:"+rlname}
    res = None
    g = rdflib.Graph()
    try:
        req = requests.get(
            LDSPDIBASEURL + "query/graph/AO_info",
            headers=headers,
            params=params,
        )
        g.parse(data=req.text, format="ttl")
        res = ao_res_from_model(g, rlname)
    except Exception as e:
        logging.error("get_buda_AO_info failed for "+rlname+": "+str(e))
    finally:
        return res

def get_outline_graph(olname):
    g = rdflib.Graph()
    try:
        req = requests.get(
            LDSPDIBASEURL + "graph/"+olname+".ttl",
            headers={"Accept": "text/turtle"}
        )
        g.parse(data=req.text, format="ttl")
        res = ao_res_from_model(g, rlname)
    except:
        logging.exception("get_outline_graph failed for "+olname+": "+str(e))
        g = None
    finally:
        return g

class OutlineEtextLookup:

    def __init__(self, olname, ielname):
        self.cls = []
        g = get_outline_graph(olname)
        if not g:
            logging.warning("no g")
            return
        for cl, _, _ in g.triples((None, BDO.contentLocationInstance, BDR[ielname])):
            mw = g.value(None, BDO.contentLocation, cl)
            mw_lname = to_lname(mw)
            volnum_start = g.value(cl, BDO.contentLocationVolume, None)
            if volnum_start:
                volnum_start = int(volnum_start)
            else:
                logging.warning("content location with no volume start, ignoring")
            volnum_end = g.value(cl, BDO.contentLocationEndVolume, None)
            if volnum_end:
                volnum_end = int(volnum_end)
            else:
                volnum_end = volnum_start
            etextnum_start = g.value(cl, BDO.contentLocationEtext, None)
            if etextnum_start:
                etextnum_start = int(etextnum_start)
            etextnum_end = g.value(cl, BDO.contentLocationEndEtext, None)
            if etextnum_end:
                etextnum_end = int(etextnum_end)
            else:
                etextnum_end = etextnum_start
            self.cls.append({"mw": mw_lname, "vnum_start": volnum_start, "vnum_end": volnum_end, "etextnum_start": etextnum_start, "etextnum_end": etextnum_end})
        
    def get_cls_for(self, vnum, etextnum):
        res = []
        # add all possible cls
        for cl in self.cls:
            if vnum == cl["vnum_end"] and vnum != cl["vnum_start"] and (not cl["etextnum_end"] or cl["etextnum_end"] >= etextnum):
                res.append(cl)
            elif vnum == cl["vnum_start"] and vnum != cl["vnum_end"] and (not cl["etextnum_start"] or cl["etextnum_start"] <= etextnum):
                res.append(cl)
            elif vnum == cl["vnum_start"] and vnum == cl["vnum_end"] and (not cl["etextnum_start"] or cl["etextnum_start"] <= etextnum and cl["etextnum_end"] >= etextnum): 
                res.append(cl)
            elif vnum < cl["vnum_end"] and vnum > cl["vnum_start"]:
                res.append(cl)
        return res

    def get_mw_for(self, vnum, etextnum):
        """
        TODO: this should be redone, it currently only works for very simple cases
        """
        cl_list = self.get_cls_for(vnum, etextnum)
        if not cl_list:
            return None
        if len(cl_list) == 1:
            return cl_list[0]["mw"]
        # take the tightest around the etextnum
        # TODO: this works only with no crossover between volumes
        tightest = 1000 # 999 is for None:None, 998 is for None:something or something:None
        tightest_idx = -1
        for i, cl in enumerate(cl_list):
            if not cl["etextnum_start"] and not cl["etextnum_end"]:
                tightness = 999
            elif not cl["etextnum_start"] or not cl["etextnum_end"]:
                tightness = 998
            else:
                tightness = cl["etextnum_end"] - cl["etextnum_start"]
            if tightness < tightest:
                tightest = tightness
                tightest_idx = i
        return cl_list[tightest_idx]["mw"]

class OutlinePageLookup:
    """
    Defines an efficient lookup structure that get built with the outline content location information
    and then returns a list of texts (mw) present on an image (defined by volume number + image number)
    """

    def __init__(self, outline_graph, w_lname, w_info):
        # Initialize a dictionary to store content locations
        self.lookup = {}
        # Additional structure to keep track of open-ended ranges
        self.open_ranges = {}
        self.vnum_to_mws = {}
        self.outline_graph = outline_graph
        self.w_lname = w_lname
        self.w_info = w_info # same format as returned by get_buda_scan_info()
        self.volnum_to_volmw = {} # volume number to mw
        self.process()

    def get_nb_img_intro(self, vnum):
        if self.w_info is None:
            return 0
        for _, ig_info in self.w_info["image_groups"].items():
            if ig_info["volume_number"] == vnum:
                return ig_info["volume_pages_bdrc_intro"]
        return 0

    def process(self):
        for s, _, cl in self.outline_graph.triples((None, BDO.contentLocation, None)):
            if (cl, BDO.contentLocationInstance, BDR[self.w_lname]) not in self.outline_graph:
                continue
            partType = self.outline_graph.value(s, BDO.partType, None)
            mw = str(s)[len(BDR_uri):]
            if partType in [BDR.PartTypeCodicologicalVolume, BDR.PartTypeVolume]:
                vnum = self.outline_graph.value(cl, BDO.contentLocationVolume, None)
                if not vnum:
                    continue
                self.volnum_to_volmw[int(vnum)] = mw
                continue
            if not partType or partType in [BDR.PartTypeSection, BDR.PartTypeChapter]:
                continue
            vnum_start = self.outline_graph.value(cl, BDO.contentLocationVolume, None)
            vnum_end = self.outline_graph.value(cl, BDO.contentLocationEndVolume, None)
            imgnum_end = self.outline_graph.value(cl, BDO.contentLocationEndPage, None)
            imgnum_start = self.outline_graph.value(cl, BDO.contentLocationPage, None)
            self.add_content_location(mw, vnum_start, vnum_end, imgnum_start, imgnum_end)

    def add_content_location(self, mw, vnum_start, vnum_end, imgnum_start, imgnum_end):
        """
        add content location information (start volume number, end volume number, start image number, end image number)
        We don't always know in advance the total number of images per volume, or the number of volumes
        imgnum_start can be None, in which case we consider it is 1 (there is no image number 0)
        imgnum_end can be None, in which case all the images after imgnum_start get associated with the mw
        there can be multiple mw associated with the same image
        """
        if vnum_start is None:
            vnum_start = 1
        if vnum_end is None:
            vnum_end = vnum_start

        if imgnum_start is None:
            imgnum_start = 1
        nb_intro_imgs = self.get_nb_img_intro(int(vnum_start))
        if int(imgnum_start) < nb_intro_imgs + 1:
            imgnum_start = nb_intro_imgs + 1

        for vnum in range(int(vnum_start), int(vnum_end) + 1):
            if vnum not in self.vnum_to_mws:
                self.vnum_to_mws[vnum] = set()
            self.vnum_to_mws[vnum].add(mw)
            vol_imgnum_end = int(imgnum_end) if vnum == int(vnum_end) and imgnum_end is not None else None
            vol_imgnum_start = int(imgnum_start) if vnum == int(vnum_start) else self.get_nb_img_intro(vnum) + 1
            if vnum not in self.lookup:
                self.lookup[vnum] = {}

            if vol_imgnum_end is None:
                if vnum not in self.open_ranges:
                    self.open_ranges[vnum] = []
                self.open_ranges[vnum].append((vol_imgnum_start, mw))
            else:
                for imgnum in range(vol_imgnum_start, vol_imgnum_end + 1):
                    if imgnum not in self.lookup[vnum]:
                        self.lookup[vnum][imgnum] = set()
                    self.lookup[vnum][imgnum].add(mw)

    def get_mw_list(self, volnum, imgnum=None):
        """
        returns a list of mws associated with a specific image
        """
        if imgnum is None:
            if volnum not in self.vnum_to_mws:
                return []
            else:
                return self.vnum_to_mws[volnum]

        mw_list = set()
        
        # Check specific image assignments
        if volnum in self.lookup and imgnum in self.lookup[volnum]:
            mw_list.update(self.lookup[volnum][imgnum])
        
        # Check open-ended ranges
        if volnum in self.open_ranges:
            for start_imgnum, mw in self.open_ranges[volnum]:
                if imgnum >= start_imgnum:
                    mw_list.add(mw)

        return mw_list

def image_group_to_folder_name(scan_id, image_group_id):
    image_group_folder_part = image_group_id
    pre, rest = image_group_id[0], image_group_id[1:]
    if pre == "I" and rest.isdigit() and len(rest) == 4:
        image_group_folder_part = rest
    return scan_id+"-"+image_group_folder_part

def send_sync_notification(ie_lname, ie_info):
    """
    sends the sync notification to editserv. ie_info is expected to have the following format:

    {
        "ocfl_version": "v1",
        "volumes": {
            "VEXX": {
                "UTXX": {
                    "nb_pages": x, (can be None)
                    "nb_characters": x,
                    "etext_num": x,
                    "src_path": "path relative to the sources/ directory in the archive"
                }
            }
        }
    }
    """
    logging.info(ie_info)
    url = EDITSERVBASEURL + f"/notifyetextsync/bdr:{ie_lname}"
    logging.info(f"send sync notification request to {url}")
    try:
        req = requests.post(url,
            json=ie_info
        )
    except Exception as e:
        logging.exception("send_sync_notification failed for "+ie_lname)